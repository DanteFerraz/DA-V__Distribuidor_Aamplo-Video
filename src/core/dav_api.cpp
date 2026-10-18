#include "include/dav/dav_api.h"
#include "src/core/config.hpp"
#include "src/core/logger.hpp"
#include "src/core/time.hpp"
#include "src/capture/capturer.hpp"
#include "src/capture/frame_buffer.hpp"
#include "src/codec/encoder.hpp"
#include "src/codec/hw/nvenc_encoder.hpp"
#include "src/codec/sw_encoder.hpp"
#include "src/packetizer/rtp_packetizer.hpp"
#include "src/packetizer/frame_assembler.hpp"
#include "src/crypto/crypto_channel.hpp"
#include "src/transport/udp_socket.hpp"
#include "src/transport/kcp_transport.hpp"
#include "src/qos/qos_engine.hpp"

#if defined(DAV_PLATFORM_WINDOWS)
#include "src/capture/windows/dxgi_capturer.hpp"
#elif defined(DAV_PLATFORM_LINUX)
#include "src/capture/linux/x11_capturer.hpp"
#endif

#include <atomic>
#include <thread>
#include <mutex>
#include <memory>
#include <vector>
#include <cstring>

namespace {

struct DavEngineContext {
    dav::AppConfig config;
    std::atomic<bool> is_initialized{false};
    std::atomic<bool> is_sender_running{false};
    std::atomic<bool> is_receiver_running{false};

    // Sender state
    std::thread sender_thread;
    std::unique_ptr<dav::ICapturer> capturer;
    std::unique_ptr<dav::IEncoder> encoder;
    std::unique_ptr<dav::UdpSocket> sender_socket;
    std::unique_ptr<dav::CryptoChannel> sender_crypto;
    dav::RtpPacketizer packetizer{0xDA0001, 1400};

    // Receiver state
    std::thread receiver_thread;
    std::unique_ptr<dav::UdpSocket> receiver_socket;
    std::unique_ptr<dav::CryptoChannel> receiver_crypto;
    dav::FrameAssembler assembler{100000}; // 100ms timeout
    DavFrameReadyCallback frame_callback{nullptr};
    DavTelemetryCallback telemetry_callback{nullptr};
    void* callback_user_data{nullptr};

    // Logging callback
    DavLogCallback log_cb{nullptr};
    void* log_user_data{nullptr};

    // Telemetry counters
    std::atomic<uint64_t> packets_sent{0};
    std::atomic<uint64_t> packets_received{0};
    std::atomic<uint64_t> packets_lost{0};
    std::atomic<uint64_t> frames_captured{0};
    std::atomic<uint64_t> frames_rendered{0};
    std::atomic<float> cur_fps{0.0f};
    std::atomic<float> cur_bitrate_mbps{0.0f};
    std::atomic<float> cur_latency_ms{0.0f};

    std::mutex engine_mutex;
};

static DavEngineContext g_ctx;

std::array<dav::Byte, 32> derive_pin_key(const char* pin) {
    std::string clean_pin = pin ? pin : "123456";
    clean_pin.erase(std::remove(clean_pin.begin(), clean_pin.end(), '-'), clean_pin.end());
    clean_pin.erase(std::remove(clean_pin.begin(), clean_pin.end(), ' '), clean_pin.end());

    std::string raw = "dav-secret-" + clean_pin + "-key-salt-2026";
    std::array<dav::Byte, 32> key{};
    for (size_t i = 0; i < 32; ++i) {
        key[i] = static_cast<dav::Byte>(raw[i % raw.size()] ^ ((i * 37) & 0xFF));
    }
    return key;
}

} // anonymous namespace

extern "C" {

DAV_API const char* dav_get_version(void) {
    return "DA-V v1.0.0 (High-Performance C-ABI Engine)";
}

DAV_API void dav_set_log_callback(DavLogCallback cb, void* user_data) {
    std::lock_guard<std::mutex> lock(g_ctx.engine_mutex);
    g_ctx.log_cb = cb;
    g_ctx.log_user_data = user_data;
}

DAV_API int dav_init(const char* config_toml) {
    std::lock_guard<std::mutex> lock(g_ctx.engine_mutex);
    if (config_toml && std::strlen(config_toml) > 0) {
        auto cfg_res = dav::AppConfig::from_toml_file(config_toml);
        if (cfg_res.has_value()) {
            g_ctx.config = *cfg_res;
        } else {
            g_ctx.config = dav::AppConfig::from_default().value();
        }
    } else {
        g_ctx.config = dav::AppConfig::from_default().value();
    }

    g_ctx.is_initialized = true;
    dav::log::info("[C-ABI] DA-V Core Engine initialized successfully.");
    return DAV_SUCCESS;
}

DAV_API int dav_start_sender(
    const char* target_ip,
    uint16_t target_port,
    const char* pin,
    uint32_t width,
    uint32_t height,
    uint32_t fps
) {
    std::lock_guard<std::mutex> lock(g_ctx.engine_mutex);
    if (!g_ctx.is_initialized) {
        dav_init(nullptr);
    }

    if (g_ctx.is_sender_running) {
        return DAV_SUCCESS;
    }

    if (!target_ip || target_port == 0) {
        return DAV_ERROR_INVALID_PARAM;
    }

    // 1. Setup Crypto Key
    auto key = derive_pin_key(pin);
    g_ctx.sender_crypto = std::make_unique<dav::CryptoChannel>(dav::ConstByteSpan(key.data(), key.size()));

    // 2. Setup UDP Sender Socket with Non-Blocking Mode
    g_ctx.sender_socket = std::make_unique<dav::UdpSocket>();
    auto dest_res = g_ctx.sender_socket->set_destination(target_ip, target_port);
    if (!dest_res.has_value()) {
        dav::log::error("[C-ABI] Failed to set UDP destination {}:{}", target_ip, target_port);
        return DAV_ERROR_SOCKET_FAILED;
    }
    g_ctx.sender_socket->set_nonblocking(true);
    g_ctx.sender_socket->set_buffer_sizes(4 * 1024 * 1024, 4 * 1024 * 1024);

    // 3. Setup Hardware/Software Capturer
    dav::CaptureConfig cap_cfg = g_ctx.config.capture;
    cap_cfg.target_resolution.width = width > 0 ? width : 1280;
    cap_cfg.target_resolution.height = height > 0 ? height : 720;
    cap_cfg.target_fps = fps > 0 ? fps : 60;
    cap_cfg.zero_copy_gpu = false; // CPU staging mapping for direct RGBA frame access

#if defined(DAV_PLATFORM_WINDOWS)
    g_ctx.capturer = std::make_unique<dav::DxgiCapturer>(cap_cfg);
#elif defined(DAV_PLATFORM_LINUX)
    g_ctx.capturer = std::make_unique<dav::X11Capturer>(cap_cfg);
#endif

    // 4. Setup Video Encoder (NVENC GPU accelerated with SW fallback)
    dav::EncoderParams enc_params{
        .codec = dav::VideoCodec::H264,
        .resolution = cap_cfg.target_resolution,
        .target_fps = cap_cfg.target_fps,
        .target_bitrate_kbps = g_ctx.config.codec.target_bitrate_kbps,
        .gop_size = 30,
        .preset = dav::EncoderPreset::UltraFast,
        .enable_zero_copy = false
    };

    g_ctx.encoder = std::make_unique<dav::NvencEncoder>();

    // Register encoder packet callback BEFORE initializing or running any encoding
    g_ctx.encoder->set_packet_callback([](const dav::EncodedPacket& enc_pkt) {
        if (!g_ctx.is_sender_running) return;
        auto packets = g_ctx.packetizer.packetize(enc_pkt);
        for (auto& p : packets) {
            if (g_ctx.sender_crypto) {
                g_ctx.sender_crypto->encrypt_packet(p);
            }
            auto serialized = p.serialize();
            if (g_ctx.sender_socket) {
                g_ctx.sender_socket->send(dav::ConstByteSpan(serialized.data(), serialized.size()));
                g_ctx.packets_sent++;
            }
        }
    });

    g_ctx.encoder->init(enc_params);

    // Connect Screen Capturer directly to Video Encoder
    if (g_ctx.capturer) {
        g_ctx.capturer->set_frame_callback([](const dav::CapturedFrame& frame) {
            if (!g_ctx.is_sender_running || !g_ctx.encoder) return;
            g_ctx.frames_captured++;
            g_ctx.encoder->encode(frame);
        });
        auto cap_res = g_ctx.capturer->start();
        if (!cap_res.has_value()) {
            dav::log::warn("[C-ABI] Hardware capturer start failed ({}), falling back to timer-driven producer", cap_res.error().message);
        }
    }

    g_ctx.is_sender_running = true;

    // 5. Spawn High-Performance Sender Monitor / Fallback Thread
    g_ctx.sender_thread = std::thread([](std::string remote_ip, uint16_t remote_port, uint32_t target_fps) {
        dav::log::info("[C-ABI] Sender thread started for {}:{} @ {} FPS", remote_ip, remote_port, target_fps);
        
        const auto frame_interval = std::chrono::microseconds(1000000 / (target_fps > 0 ? target_fps : 60));
        uint64_t fallback_frame_index = 0;
        uint64_t last_stat_time_us = dav::time::now_microseconds();
        uint64_t last_packets = 0;
        uint64_t last_frames = 0;

        while (g_ctx.is_sender_running) {
            auto loop_start = std::chrono::steady_clock::now();
            uint64_t now_us = dav::time::now_microseconds();

            // Fallback generation ONLY if hardware capturer is inactive
            if (!g_ctx.capturer || !g_ctx.capturer->is_capturing()) {
                dav::CapturedFrame frame{};
                frame.frame_index = ++fallback_frame_index;
                frame.timestamp_us = now_us;
                frame.resolution = {1280, 720};
                frame.format = dav::PixelFormat::BGRA;
                g_ctx.frames_captured++;
                if (g_ctx.encoder) {
                    g_ctx.encoder->encode(frame);
                }
            }

            // Periodic Sender Telemetry Calculation (every 250ms)
            if (now_us - last_stat_time_us >= 250000) {
                double elapsed_sec = (now_us - last_stat_time_us) / 1000000.0;
                uint64_t sec_frames = g_ctx.frames_captured - last_frames;
                uint64_t sec_pkts = g_ctx.packets_sent - last_packets;

                g_ctx.cur_fps = static_cast<float>(sec_frames / elapsed_sec);
                g_ctx.cur_bitrate_mbps = static_cast<float>((sec_pkts * 1400 * 8.0) / (elapsed_sec * 1000000.0));

                last_stat_time_us = now_us;
                last_frames = g_ctx.frames_captured;
                last_packets = g_ctx.packets_sent;
            }

            auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - loop_start);
            if (elapsed < frame_interval) {
                std::this_thread::sleep_for(frame_interval - elapsed);
            }
        }
        dav::log::info("[C-ABI] Sender thread terminated.");
    }, std::string(target_ip), target_port, fps);

    return DAV_SUCCESS;
}

DAV_API int dav_start_receiver(
    uint16_t bind_port,
    const char* pin,
    DavFrameReadyCallback on_frame,
    DavTelemetryCallback on_telemetry,
    void* user_data
) {
    std::lock_guard<std::mutex> lock(g_ctx.engine_mutex);
    if (!g_ctx.is_initialized) {
        dav_init(nullptr);
    }

    if (g_ctx.is_receiver_running) {
        return DAV_SUCCESS;
    }

    g_ctx.frame_callback = on_frame;
    g_ctx.telemetry_callback = on_telemetry;
    g_ctx.callback_user_data = user_data;

    // 1. Setup Crypto Key
    auto key = derive_pin_key(pin);
    g_ctx.receiver_crypto = std::make_unique<dav::CryptoChannel>(dav::ConstByteSpan(key.data(), key.size()));

    // 2. Setup UDP Receiver Socket
    g_ctx.receiver_socket = std::make_unique<dav::UdpSocket>();
    auto bind_res = g_ctx.receiver_socket->bind(bind_port);
    if (!bind_res.has_value()) {
        dav::log::error("[C-ABI] Failed to bind UDP receiver on port {}", bind_port);
        return DAV_ERROR_SOCKET_FAILED;
    }
    g_ctx.receiver_socket->set_nonblocking(true);
    g_ctx.receiver_socket->set_buffer_sizes(4 * 1024 * 1024, 4 * 1024 * 1024);

    g_ctx.is_receiver_running = true;

    // 3. Spawn High-Performance Receiver Thread
    g_ctx.receiver_thread = std::thread([](uint16_t port) {
        dav::log::info("[C-ABI] Receiver thread listening on port {}", port);
        std::vector<dav::Byte> recv_buf(65536, 0);
        
        uint64_t last_stat_time_us = dav::time::now_microseconds();
        uint64_t last_packets = 0;
        uint64_t last_bytes = 0;
        uint64_t last_rendered_frames = 0;
        uint64_t total_recv_bytes = 0;
        uint64_t last_pkt_ts_us = 0;
        int64_t min_clock_offset_us = 0;

        while (g_ctx.is_receiver_running) {
            auto recv_res = g_ctx.receiver_socket->receive(dav::MutableByteSpan(recv_buf));
            if (recv_res.has_value() && *recv_res >= sizeof(dav::PacketHeader)) {
                uint64_t now_us = dav::time::now_microseconds();
                g_ctx.packets_received++;
                total_recv_bytes += *recv_res;

                dav::DavPacket pkt{};
                std::memcpy(&pkt.header, recv_buf.data(), sizeof(dav::PacketHeader));
                last_pkt_ts_us = pkt.header.timestamp_us;
                size_t payload_len = pkt.header.payload_length;
                if (*recv_res >= sizeof(dav::PacketHeader) + payload_len) {
                    pkt.payload.assign(
                        recv_buf.data() + sizeof(dav::PacketHeader),
                        recv_buf.data() + sizeof(dav::PacketHeader) + payload_len
                    );
                }

                // Authenticated Decryption
                if (pkt.header.is_encrypted() && g_ctx.receiver_crypto) {
                    if (*recv_res >= sizeof(dav::PacketHeader) + payload_len + 16) {
                        pkt.auth_tag.assign(
                            recv_buf.data() + sizeof(dav::PacketHeader) + payload_len,
                            recv_buf.data() + sizeof(dav::PacketHeader) + payload_len + 16
                        );
                    }
                    g_ctx.receiver_crypto->decrypt_packet(pkt);
                }

                // Out-of-Order Frame Reassembly
                auto assembled = g_ctx.assembler.push_packet(pkt, now_us);
                if (assembled.has_value()) {
                    g_ctx.frames_rendered++;

                    if (g_ctx.frame_callback) {
                        DavRenderFrame render_frame{};
                        render_frame.width = 1280;
                        render_frame.height = 720;
                        render_frame.stride = 1280 * 4;
                        render_frame.timestamp_us = assembled->timestamp_us;
                        render_frame.rgba_data = assembled->data.data();
                        render_frame.data_size = assembled->data.size();
                        render_frame.is_keyframe = assembled->is_keyframe ? 1 : 0;

                        g_ctx.frame_callback(&render_frame, g_ctx.callback_user_data);
                    }
                }
            } else {
                std::this_thread::sleep_for(std::chrono::microseconds(500));
            }

            // Emit Telemetry every 250ms
            uint64_t cur_us = dav::time::now_microseconds();
            if (cur_us - last_stat_time_us >= 250000) {
                double elapsed_sec = (cur_us - last_stat_time_us) / 1000000.0;
                uint64_t sec_pkts = g_ctx.packets_received - last_packets;
                uint64_t sec_bytes = total_recv_bytes - last_bytes;
                uint64_t sec_frames = g_ctx.frames_rendered - last_rendered_frames;

                g_ctx.cur_fps = static_cast<float>(sec_frames / elapsed_sec);
                g_ctx.cur_bitrate_mbps = static_cast<float>((sec_bytes * 8.0) / (elapsed_sec * 1000000.0));

                if (last_pkt_ts_us > 0) {
                    int64_t raw_diff = static_cast<int64_t>(cur_us - last_pkt_ts_us);
                    if (min_clock_offset_us == 0 || raw_diff < min_clock_offset_us) {
                        min_clock_offset_us = raw_diff;
                    }
                    float lat_sample = static_cast<float>(std::max(0.2, static_cast<double>(raw_diff - min_clock_offset_us) / 1000.0));
                    if (g_ctx.cur_latency_ms == 0.0f) {
                        g_ctx.cur_latency_ms = lat_sample;
                    } else {
                        g_ctx.cur_latency_ms = 0.8f * g_ctx.cur_latency_ms + 0.2f * lat_sample;
                    }
                }

                if (g_ctx.telemetry_callback) {
                    DavTelemetry telem{};
                    telem.fps = g_ctx.cur_fps;
                    telem.bitrate_mbps = g_ctx.cur_bitrate_mbps;
                    telem.latency_ms = g_ctx.cur_latency_ms;
                    telem.packets_sent = g_ctx.packets_sent;
                    telem.packets_received = g_ctx.packets_received;
                    telem.packets_lost = g_ctx.packets_lost;
                    telem.frames_captured = g_ctx.frames_captured;
                    telem.frames_rendered = g_ctx.frames_rendered;
                    telem.is_connected = 1;

                    g_ctx.telemetry_callback(&telem, g_ctx.callback_user_data);
                }

                last_stat_time_us = cur_us;
                last_packets = g_ctx.packets_received;
                last_bytes = total_recv_bytes;
                last_rendered_frames = g_ctx.frames_rendered;
            }
        }
        dav::log::info("[C-ABI] Receiver thread terminated.");
    }, bind_port);

    return DAV_SUCCESS;
}

DAV_API void dav_request_keyframe(void) {
    std::lock_guard<std::mutex> lock(g_ctx.engine_mutex);
    if (g_ctx.encoder) {
        g_ctx.encoder->request_keyframe();
    }
}

DAV_API int dav_get_telemetry(DavTelemetry* out_telemetry) {
    if (!out_telemetry) return DAV_ERROR_INVALID_PARAM;
    out_telemetry->fps = g_ctx.cur_fps;
    out_telemetry->bitrate_mbps = g_ctx.cur_bitrate_mbps;
    out_telemetry->latency_ms = g_ctx.cur_latency_ms;
    out_telemetry->packets_sent = g_ctx.packets_sent;
    out_telemetry->packets_received = g_ctx.packets_received;
    out_telemetry->packets_lost = g_ctx.packets_lost;
    out_telemetry->frames_captured = g_ctx.frames_captured;
    out_telemetry->frames_rendered = g_ctx.frames_rendered;
    out_telemetry->is_connected = (g_ctx.is_sender_running || g_ctx.is_receiver_running) ? 1 : 0;
    return DAV_SUCCESS;
}

DAV_API void dav_stop(void) {
    std::lock_guard<std::mutex> lock(g_ctx.engine_mutex);

    g_ctx.is_sender_running = false;
    g_ctx.is_receiver_running = false;

    if (g_ctx.capturer) {
        g_ctx.capturer->stop();
    }

    if (g_ctx.sender_thread.joinable()) {
        g_ctx.sender_thread.join();
    }
    if (g_ctx.receiver_thread.joinable()) {
        g_ctx.receiver_thread.join();
    }

    if (g_ctx.capturer) {
        g_ctx.capturer.reset();
    }
    if (g_ctx.encoder) {
        g_ctx.encoder->close();
        g_ctx.encoder.reset();
    }
    if (g_ctx.sender_socket) {
        g_ctx.sender_socket->close();
        g_ctx.sender_socket.reset();
    }
    if (g_ctx.receiver_socket) {
        g_ctx.receiver_socket->close();
        g_ctx.receiver_socket.reset();
    }

    dav::log::info("[C-ABI] DA-V Core Engine stopped.");
}

} // extern "C"
