#include "src/qos/jitter_buffer.hpp"
#include <algorithm>
#include <cmath>

namespace dav {

JitterBuffer::JitterBuffer(uint32_t min_delay_ms, uint32_t max_delay_ms)
    : min_delay_ms_(min_delay_ms),
      max_delay_ms_(max_delay_ms),
      target_delay_ms_(std::max(min_delay_ms, 10u)) {
}

void JitterBuffer::reset() {
    buffer_.clear();
    mean_transit_us_ = 0.0;
    m2_transit_us_ = 0.0;
    sample_count_ = 0;
    current_jitter_ms_ = 1.0;
    target_delay_ms_ = min_delay_ms_;
}

void JitterBuffer::update_jitter(uint64_t send_time_us, uint64_t arrival_time_us) {
    if (last_arrival_time_us_ > 0 && last_send_time_us_ > 0) {
        int64_t transit_us = static_cast<int64_t>(arrival_time_us - send_time_us);
        sample_count_++;

        // Welford's algorithm for online variance and mean
        double delta = static_cast<double>(transit_us) - mean_transit_us_;
        mean_transit_us_ += delta / sample_count_;
        double delta2 = static_cast<double>(transit_us) - mean_transit_us_;
        m2_transit_us_ += delta * delta2;

        if (sample_count_ > 10) {
            double variance_us2 = m2_transit_us_ / (sample_count_ - 1);
            double std_dev_ms = std::sqrt(variance_us2) / 1000.0;
            current_jitter_ms_ = std_dev_ms;

            // Target playout delay = 2x std_dev + base delay
            uint32_t recommended_delay = static_cast<uint32_t>(min_delay_ms_ + 2.0 * std_dev_ms);
            target_delay_ms_ = std::clamp(recommended_delay, min_delay_ms_, max_delay_ms_);
        }
    }

    last_send_time_us_ = send_time_us;
    last_arrival_time_us_ = arrival_time_us;
}

void JitterBuffer::push_packet(const DavPacket& packet, uint64_t arrival_time_us) {
    update_jitter(packet.header.timestamp_us, arrival_time_us);

    uint64_t playout_time_us = arrival_time_us + (static_cast<uint64_t>(target_delay_ms_) * 1000);
    buffer_[packet.header.sequence_number] = {playout_time_us, packet};
}

std::optional<DavPacket> JitterBuffer::pop_packet(uint64_t current_time_us) {
    if (buffer_.empty()) return std::nullopt;

    auto it = buffer_.begin();
    if (current_time_us >= it->second.first) {
        DavPacket packet = std::move(it->second.second);
        buffer_.erase(it);
        return packet;
    }
    return std::nullopt;
}

} // namespace dav
