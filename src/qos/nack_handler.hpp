#pragma once

#include "src/core/types.hpp"
#include <map>
#include <vector>
#include <cstdint>

namespace dav {

struct NackRequest {
    uint32_t sequence_number{0};
    uint64_t last_requested_us{0};
    uint8_t retry_count{0};
};

class NackHandler {
public:
    explicit NackHandler(double rtt_ms = 20.0, uint8_t max_retries = 3);

    void on_packet_received(uint32_t sequence_number, uint64_t now_us);
    std::vector<uint32_t> get_pending_nacks(uint64_t now_us);
    void update_rtt(double rtt_ms);

    [[nodiscard]] uint64_t get_total_nacks_sent() const noexcept { return total_nacks_sent_; }
    [[nodiscard]] size_t get_missing_count() const noexcept { return missing_packets_.size(); }

    void reset();

private:
    double rtt_ms_;
    uint8_t max_retries_;
    uint32_t highest_sequence_number_{0};
    bool initialized_{false};

    std::map<uint32_t, NackRequest> missing_packets_;
    uint64_t total_nacks_sent_{0};
};

} // namespace dav
