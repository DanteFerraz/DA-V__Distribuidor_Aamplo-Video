#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include "src/packetizer/packet.hpp"
#include <vector>
#include <cstdint>

namespace dav {

struct FecBlock {
    uint32_t block_id{0};
    uint8_t data_shards{10};
    uint8_t parity_shards{2};
    std::vector<DavPacket> packets;
    std::vector<DavPacket> parity_packets;
};

class FecHandler {
public:
    explicit FecHandler(uint8_t data_shards = 10, uint8_t parity_shards = 2);

    // Sender: generates parity packets for a group of data packets
    std::vector<DavPacket> generate_parity(const std::vector<DavPacket>& data_packets, uint32_t block_id);

    // Receiver: feeds received data/parity packets and attempts to recover lost packets
    std::vector<DavPacket> try_recover(const std::vector<DavPacket>& received_packets, uint8_t total_expected);

    void set_overhead_ratio(uint8_t data_shards, uint8_t parity_shards);
    [[nodiscard]] double get_overhead_percentage() const noexcept;

private:
    uint8_t data_shards_;
    uint8_t parity_shards_;
};

} // namespace dav
