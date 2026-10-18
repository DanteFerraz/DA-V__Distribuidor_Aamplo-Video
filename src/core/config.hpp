#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include <string>
#include <vector>
#include <cstdint>

namespace dav {

struct TransportConfig {
    uint16_t bind_port{9000};
    std::string remote_host{"127.0.0.1"};
    uint16_t remote_port{9000};
    uint32_t mtu{1400};
    int kcp_nodelay{1};      // 1 = enabled
    int kcp_interval{10};    // 10ms internal clock update
    int kcp_resend{2};      // fast resend on 2 acks
    int kcp_nc{1};          // 1 = disable congestion window (no cwnd limit)
    uint32_t snd_wnd{128};
    uint32_t rcv_wnd{512};
    uint32_t conv_id{0x11223344};
};

struct CaptureConfig {
    uint32_t display_index{0};
    Resolution target_resolution{1920, 1080};
    uint32_t target_fps{60};
    bool show_cursor{true};
    bool zero_copy_gpu{true};
};

struct CodecConfig {
    CodecType codec{CodecType::H264};
    bool prefer_hardware{true};
    HardwareVendor preferred_vendor{HardwareVendor::NVIDIA};
    uint32_t target_bitrate_kbps{8000};
    uint32_t min_bitrate_kbps{1000};
    uint32_t max_bitrate_kbps{25000};
    uint32_t gop_size{60};     // Keyframe every 60 frames (1s @ 60fps)
    std::string preset{"ultrafast"}; // low latency
    std::string tune{"zerolatency"};
};

struct QosConfig {
    bool enable_fec{true};
    uint32_t fec_data_shards{10};
    uint32_t fec_parity_shards{2}; // 20% overhead
    bool enable_abr{true};
    bool enable_nack{true};
    uint32_t jitter_buffer_min_ms{5};
    uint32_t jitter_buffer_max_ms{100};
    uint8_t dscp_video{0x20};  // CS4
    uint8_t dscp_control{0x30}; // CS6
};

struct CryptoConfig {
    bool enabled{true};
    std::string psk_secret{"dav-secret-master-key-32bytes!!"};
};

struct SignalingConfig {
    std::string server_url{"ws://127.0.0.1:8765"};
    std::string session_id{"dav-session-default"};
    std::vector<std::string> stun_servers{"stun:stun.l.google.com:19302"};
    bool auto_reconnect{true};
    uint32_t reconnect_interval_ms{1000};
    uint32_t max_reconnect_attempts{10};
};

struct MetricsConfig {
    bool enabled{true};
    uint16_t prometheus_port{9200};
    std::string path{"/metrics"};
};

struct AppConfig {
    std::string node_id{"dav-node-1"};
    bool is_sender{true};
    TransportConfig transport;
    CaptureConfig capture;
    CodecConfig codec;
    QosConfig qos;
    CryptoConfig crypto;
    SignalingConfig signaling;
    MetricsConfig metrics;

    static Result<AppConfig> from_toml_file(std::string_view filepath);
    static Result<AppConfig> from_default();
    [[nodiscard]] std::string to_toml_string() const;
};

} // namespace dav
