#pragma once

#include "src/core/types.hpp"
#include "src/packetizer/packet.hpp"
#include <map>
#include <optional>
#include <cstdint>

namespace dav {

class JitterBuffer {
public:
    explicit JitterBuffer(uint32_t min_delay_ms = 5, uint32_t max_delay_ms = 100);

    void push_packet(const DavPacket& packet, uint64_t arrival_time_us);
    std::optional<DavPacket> pop_packet(uint64_t current_time_us);

    [[nodiscard]] double get_current_jitter_ms() const noexcept { return current_jitter_ms_; }
    [[nodiscard]] uint32_t get_target_delay_ms() const noexcept { return target_delay_ms_; }
    [[nodiscard]] size_t get_buffered_packets_count() const noexcept { return buffer_.size(); }

    void reset();

private:
    void update_jitter(uint64_t send_time_us, uint64_t arrival_time_us);

    uint32_t min_delay_ms_;
    uint32_t max_delay_ms_;
    uint32_t target_delay_ms_{10};

    // Welford variance tracking
    double mean_transit_us_{0.0};
    double m2_transit_us_{0.0};
    uint64_t sample_count_{0};
    double current_jitter_ms_{1.0};

    uint64_t last_send_time_us_{0};
    uint64_t last_arrival_time_us_{0};

    // Buffer sorted by sequence number
    std::map<uint32_t, std::pair<uint64_t, DavPacket>> buffer_; // seq -> (scheduled_playout_us, packet)
};

} // namespace dav
