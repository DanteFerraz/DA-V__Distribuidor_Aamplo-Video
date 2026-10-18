#include "src/core/config.hpp"
#include "src/core/logger.hpp"
#include "src/core/time.hpp"
#include "src/capture/capturer.hpp"
#include "src/capture/frame_buffer.hpp"
#include "src/codec/encoder.hpp"
#include "src/codec/hw/nvenc_encoder.hpp"
#include "src/packetizer/rtp_packetizer.hpp"
#include "src/session/session_manager.hpp"
#include "src/metrics/metrics_registry.hpp"
#include "src/metrics/http_exporter.hpp"

#if defined(DAV_PLATFORM_WINDOWS)
#include "src/capture/windows/dxgi_capturer.hpp"
#elif defined(DAV_PLATFORM_LINUX)
#include "src/capture/linux/x11_capturer.hpp"
#endif

#include <csignal>
#include <iostream>
#include <memory>
#include <atomic>
#include <thread>

static std::atomic<bool> g_running{true};

void signal_handler(int sig) {
    (void)sig;
    dav::log::info("Received termination signal, shutting down DA-V gracefully...");
    g_running = false;
}

int main(int argc, char* argv[]) {
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    dav::log::info("=========================================================");
    dav::log::info("  DA-V: Distribuidor Aamplo - Video Streaming Service  ");
    dav::log::info("  High-Performance Ultra-Low Latency QoS Backend Core    ");
    dav::log::info("=========================================================");

    // 1. Load Configuration
    std::string config_path = (argc > 1) ? argv[1] : "dav.toml";
    auto config_res = dav::AppConfig::from_toml_file(config_path);
    dav::AppConfig config = config_res.value_or(dav::AppConfig::from_default().value());

    dav::log::info("Node ID: {} | Mode: {}", config.node_id, config.is_sender ? "SENDER" : "RECEIVER");

    // 2. Start Prometheus Metrics Exporter
    dav::HttpMetricsExporter metrics_exporter(config.metrics.prometheus_port);
    if (config.metrics.enabled) {
        metrics_exporter.start();
    }

    // 3. Initialize Multi-Peer Session Manager
    dav::SessionManager session_mgr(config);

    // 4. Initialize RTP Packetizer
    dav::RtpPacketizer packetizer(0xDA0001, config.transport.mtu);

    // 5. Initialize Video Encoder (NVIDIA NVENC HW or x264 SW)
    dav::EncoderParams enc_params{
        .codec = config.codec.codec,
        .resolution = config.capture.target_resolution,
        .target_fps = config.capture.target_fps,
        .target_bitrate_kbps = config.codec.target_bitrate_kbps,
        .gop_size = config.codec.gop_size,
        .preset = config.codec.preset
    };

    auto encoder = std::make_unique<dav::NvencEncoder>();
    encoder->init(enc_params);
    dav::log::info("Active Encoder: {}", encoder->get_encoder_name());

    encoder->set_packet_callback([&](const dav::EncodedPacket& enc_pkt) {
        dav::MetricsRegistry::instance().increment_frames_encoded(1);
        dav::MetricsRegistry::instance().set_encode_bitrate_bps(enc_pkt.data.size() * 8 * config.capture.target_fps);

        // Fragment across MTU boundaries (Wire protocol format)
        auto packets = packetizer.packetize(enc_pkt);
        dav::MetricsRegistry::instance().increment_packets_sent(packets.size());

        // Broadcast to all active peer sessions
        session_mgr.broadcast_frame(packets);
    });

    // 6. Initialize Frame Ring Buffer
    dav::FrameRingBuffer frame_ring(8);

    // 7. Initialize Platform-Specific Screen Capturer
    std::unique_ptr<dav::ICapturer> capturer;
#if defined(DAV_PLATFORM_WINDOWS)
    capturer = std::make_unique<dav::DxgiCapturer>(config.capture);
#elif defined(DAV_PLATFORM_LINUX)
    capturer = std::make_unique<dav::X11Capturer>(config.capture);
#endif

    if (config.is_sender && capturer) {
        capturer->set_frame_callback([&](const dav::CapturedFrame& frame) {
            dav::MetricsRegistry::instance().increment_frames_captured(1);
            dav::MetricsRegistry::instance().set_capture_fps(config.capture.target_fps);
            frame_ring.push(dav::CapturedFrame(frame));
        });

        capturer->start();
        dav::log::info("Active Capturer: {}", capturer->get_backend_name());
    }

    // 8. Main Loop
    dav::log::info("DA-V Service Core is RUNNING. Press Ctrl+C to terminate.");
    
    while (g_running) {
        uint64_t now_us = dav::time::now_microseconds();

        // Process pending frames from capture ring buffer
        if (auto frame = frame_ring.pop()) {
            encoder->encode(*frame);
        }

        // Update sessions and transport loops
        session_mgr.update_all(now_us);
        dav::MetricsRegistry::instance().set_active_sessions(static_cast<uint32_t>(session_mgr.get_active_session_count()));

        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    // 9. Shutdown
    dav::log::info("Stopping DA-V components...");
    if (capturer) capturer->stop();
    encoder->close();
    metrics_exporter.stop();
    dav::log::info("DA-V shutdown complete.");

    return 0;
}
