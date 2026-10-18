#include "src/qos/nack_handler.hpp"
#include <algorithm>

namespace dav {

NackHandler::NackHandler(double rtt_ms, uint8_t max_retries)
    : rtt_ms_(std::max(rtt_ms, 5.0)),
      max_retries_(max_retries > 0 ? max_retries : 3) {
}

void NackHandler::reset() {
    missing_packets_.clear();
    highest_sequence_number_ = 0;
    initialized_ = false;
    total_nacks_sent_ = 0;
}

void NackHandler::update_rtt(double rtt_ms) {
    rtt_ms_ = std::max(rtt_ms, 5.0);
}

void NackHandler::on_packet_received(uint32_t sequence_number, uint64_t now_us) {
    if (!initialized_) {
        highest_sequence_number_ = sequence_number;
        initialized_ = true;
        return;
    }

    // If packet was previously missing, remove it from NACK list
    missing_packets_.erase(sequence_number);

    // If new highest sequence number, check for gaps
    if (sequence_number > highest_sequence_number_) {
        for (uint32_t seq = highest_sequence_number_ + 1; seq < sequence_number; ++seq) {
            missing_packets_[seq] = NackRequest{
                .sequence_number = seq,
                .last_requested_us = 0,
                .retry_count = 0
            };
        }
        highest_sequence_number_ = sequence_number;
    }
}

std::vector<uint32_t> NackHandler::get_pending_nacks(uint64_t now_us) {
    std::vector<uint32_t> nacks;
    const uint64_t rtt_us = static_cast<uint64_t>(rtt_ms_ * 1000.0 * 1.2); // 1.2x RTT debounce

    auto it = missing_packets_.begin();
    while (it != missing_packets_.end()) {
        if (it->second.retry_count >= max_retries_) {
            // Give up on this packet after max retries
            it = missing_packets_.erase(it);
        } else if (it->second.last_requested_us == 0 || (now_us - it->second.last_requested_us) >= rtt_us) {
            nacks.push_back(it->first);
            it->second.last_requested_us = now_us;
            it->second.retry_count++;
            total_nacks_sent_++;
            ++it;
        } else {
            ++it;
        }
    }

    return nacks;
}

} // namespace dav
