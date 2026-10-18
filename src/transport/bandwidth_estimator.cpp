#include "src/transport/bandwidth_estimator.hpp"
#include <algorithm>
#include <cmath>

namespace dav {

BandwidthEstimator::BandwidthEstimator(uint32_t min_bitrate_bps, uint32_t max_bitrate_bps)
    : min_bitrate_bps_(min_bitrate_bps),
      max_bitrate_bps_(max_bitrate_bps),
      current_bitrate_bps_(std::clamp(8000000u, min_bitrate_bps, max_bitrate_bps)) {
}

void BandwidthEstimator::reset() {
    current_bitrate_bps_ = std::clamp(8000000u, min_bitrate_bps_, max_bitrate_bps_);
    smoothed_rtt_ms_ = 10.0;
    packet_loss_rate_ = 0.0;
    jitter_ms_ = 0.0;
    state_ = NetworkState::Normal;
    delivery_window_.clear();
    window_bytes_ = 0;
}

void BandwidthEstimator::on_packet_sent(size_t bytes, uint64_t timestamp_us) {
    (void)bytes;
    last_send_time_us_ = timestamp_us;
}

void BandwidthEstimator::on_packet_received(size_t bytes, uint64_t timestamp_us, uint64_t send_time_us) {
    delivery_window_.push_back({timestamp_us, bytes});
    window_bytes_ += bytes;

    // Keep sliding window of 500ms (500,000 µs)
    while (!delivery_window_.empty() && (timestamp_us - delivery_window_.front().first) > 500000) {
        window_bytes_ -= delivery_window_.front().second;
        delivery_window_.pop_front();
    }

    if (last_recv_time_us_ > 0 && last_send_time_us_ > 0) {
        int64_t send_delta = static_cast<int64_t>(send_time_us - last_send_time_us_);
        int64_t recv_delta = static_cast<int64_t>(timestamp_us - last_recv_time_us_);
        double delay_gradient = static_cast<double>(recv_delta - send_delta) / 1000.0; // in ms
        update_trend(delay_gradient);
    }

    last_recv_time_us_ = timestamp_us;
}

void BandwidthEstimator::update_trend(double delay_gradient) {
    constexpr double OveruseThresholdMs = 12.0;
    constexpr double UnderuseThresholdMs = -8.0;

    if (delay_gradient > OveruseThresholdMs) {
        state_ = NetworkState::Overusing;
        // Congestion detected -> Backoff (Multiplicative Decrease: -15%)
        current_bitrate_bps_ = static_cast<uint32_t>(current_bitrate_bps_ * 0.85);
    } else if (delay_gradient < UnderuseThresholdMs) {
        state_ = NetworkState::Underusing;
        // Channel clearing -> Additive Increase (+5%)
        current_bitrate_bps_ = static_cast<uint32_t>(current_bitrate_bps_ * 1.05 + 100000);
    } else {
        state_ = NetworkState::Normal;
        // Steady channel -> Moderate probe (+2%)
        current_bitrate_bps_ = static_cast<uint32_t>(current_bitrate_bps_ * 1.02);
    }

    current_bitrate_bps_ = std::clamp(current_bitrate_bps_, min_bitrate_bps_, max_bitrate_bps_);
}

void BandwidthEstimator::on_feedback(double rtt_ms, double loss_rate) {
    smoothed_rtt_ms_ = 0.8 * smoothed_rtt_ms_ + 0.2 * rtt_ms;
    packet_loss_rate_ = 0.8 * packet_loss_rate_ + 0.2 * loss_rate;

    // Loss-based backoff
    if (packet_loss_rate_ > 0.05) { // Loss > 5%
        current_bitrate_bps_ = static_cast<uint32_t>(current_bitrate_bps_ * (1.0 - 0.5 * packet_loss_rate_));
    } else if (packet_loss_rate_ < 0.01 && state_ == NetworkState::Normal) {
        current_bitrate_bps_ = static_cast<uint32_t>(current_bitrate_bps_ * 1.03);
    }

    current_bitrate_bps_ = std::clamp(current_bitrate_bps_, min_bitrate_bps_, max_bitrate_bps_);
}

BandwidthEstimate BandwidthEstimator::get_estimate() const noexcept {
    return BandwidthEstimate{
        .estimated_bitrate_bps = current_bitrate_bps_,
        .rtt_ms = smoothed_rtt_ms_,
        .packet_loss_rate = packet_loss_rate_,
        .jitter_ms = jitter_ms_,
        .state = state_
    };
}

uint32_t BandwidthEstimator::get_target_bitrate_bps() const noexcept {
    return current_bitrate_bps_;
}

} // namespace dav
