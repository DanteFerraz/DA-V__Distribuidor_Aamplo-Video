#pragma once

#include "src/core/types.hpp"
#include <cstdint>
#include <chrono>
#include <vector>
#include <deque>

namespace dav {

enum class NetworkState {
    Normal,
    Underusing,
    Overusing
};

struct BandwidthEstimate {
    uint32_t estimated_bitrate_bps{8000000}; // Default 8 Mbps
    double rtt_ms{0.0};
    double packet_loss_rate{0.0};
    double jitter_ms{0.0};
    NetworkState state{NetworkState::Normal};
};

class BandwidthEstimator {
public:
    BandwidthEstimator(uint32_t min_bitrate_bps = 500000, uint32_t max_bitrate_bps = 50000000);

    void on_packet_sent(size_t bytes, uint64_t timestamp_us);
    void on_packet_received(size_t bytes, uint64_t timestamp_us, uint64_t send_time_us);
    void on_feedback(double rtt_ms, double loss_rate);

    [[nodiscard]] BandwidthEstimate get_estimate() const noexcept;
    [[nodiscard]] uint32_t get_target_bitrate_bps() const noexcept;

    void reset();

private:
    void update_trend(double delay_gradient);

    uint32_t min_bitrate_bps_;
    uint32_t max_bitrate_bps_;
    uint32_t current_bitrate_bps_;

    double smoothed_rtt_ms_{10.0};
    double packet_loss_rate_{0.0};
    double jitter_ms_{0.0};
    NetworkState state_{NetworkState::Normal};

    uint64_t last_send_time_us_{0};
    uint64_t last_recv_time_us_{0};

    // Bitrate calculation window
    std::deque<std::pair<uint64_t, size_t>> delivery_window_;
    uint64_t window_bytes_{0};
};

} // namespace dav
