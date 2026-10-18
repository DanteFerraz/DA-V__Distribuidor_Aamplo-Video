#pragma once

#include "src/core/types.hpp"
#include <atomic>
#include <string>
#include <sstream>
#include <mutex>
#include <map>

namespace dav {

class MetricsRegistry {
public:
    static MetricsRegistry& instance();

    // Gauges
    void set_capture_fps(double fps) noexcept;
    void set_encode_fps(double fps) noexcept;
    void set_encode_bitrate_bps(uint64_t bps) noexcept;
    void set_transport_rtt_ms(double rtt_ms) noexcept;
    void set_transport_loss_rate(double loss) noexcept;
    void set_jitter_ms(double jitter_ms) noexcept;
    void set_fec_overhead_pct(double pct) noexcept;
    void set_active_sessions(uint32_t count) noexcept;

    // Counters
    void increment_frames_captured(uint64_t count = 1) noexcept;
    void increment_frames_encoded(uint64_t count = 1) noexcept;
    void increment_packets_sent(uint64_t count = 1) noexcept;
    void increment_packets_received(uint64_t count = 1) noexcept;
    void increment_nacks_sent(uint64_t count = 1) noexcept;
    void increment_frames_dropped(uint64_t count = 1) noexcept;

    // Prometheus Text Exposition Format Exporter
    [[nodiscard]] std::string export_prometheus_text() const;

private:
    MetricsRegistry() = default;

    std::atomic<double> capture_fps_{0.0};
    std::atomic<double> encode_fps_{0.0};
    std::atomic<uint64_t> encode_bitrate_bps_{0};
    std::atomic<double> rtt_ms_{0.0};
    std::atomic<double> loss_rate_{0.0};
    std::atomic<double> jitter_ms_{0.0};
    std::atomic<double> fec_overhead_pct_{0.0};
    std::atomic<uint32_t> active_sessions_{0};

    std::atomic<uint64_t> frames_captured_total_{0};
    std::atomic<uint64_t> frames_encoded_total_{0};
    std::atomic<uint64_t> packets_sent_total_{0};
    std::atomic<uint64_t> packets_received_total_{0};
    std::atomic<uint64_t> nacks_sent_total_{0};
    std::atomic<uint64_t> frames_dropped_total_{0};
};

} // namespace dav
