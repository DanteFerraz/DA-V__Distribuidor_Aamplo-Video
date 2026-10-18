#include "src/qos/fec.hpp"
#include <algorithm>

namespace dav {

FecHandler::FecHandler(uint8_t data_shards, uint8_t parity_shards)
    : data_shards_(data_shards > 0 ? data_shards : 10),
      parity_shards_(parity_shards > 0 ? parity_shards : 2) {
}

void FecHandler::set_overhead_ratio(uint8_t data_shards, uint8_t parity_shards) {
    if (data_shards > 0) data_shards_ = data_shards;
    if (parity_shards > 0) parity_shards_ = parity_shards;
}

double FecHandler::get_overhead_percentage() const noexcept {
    return (static_cast<double>(parity_shards_) / data_shards_) * 100.0;
}

std::vector<DavPacket> FecHandler::generate_parity(const std::vector<DavPacket>& data_packets, uint32_t block_id) {
    std::vector<DavPacket> parity_packets;
    if (data_packets.empty()) return parity_packets;

    size_t max_payload = 0;
    for (const auto& p : data_packets) {
        max_payload = std::max(max_payload, p.payload.size());
    }

    for (uint8_t p_idx = 0; p_idx < parity_shards_; ++p_idx) {
        DavPacket parity{};
        parity.header.version = 1;
        parity.header.packet_type = 1; // FEC Parity
        parity.header.set_fec(true);
        parity.header.sequence_number = 0xFEC00000 | (block_id << 4) | p_idx;
        parity.header.frame_id = block_id;
        parity.header.fragment_index = p_idx;
        parity.header.fragment_total = parity_shards_;
        parity.header.payload_length = static_cast<uint32_t>(max_payload);

        parity.payload.resize(max_payload, 0);

        // XOR Parity generation across all data packets in block
        for (const auto& data_p : data_packets) {
            for (size_t i = 0; i < data_p.payload.size(); ++i) {
                parity.payload[i] ^= data_p.payload[i];
            }
        }

        parity_packets.push_back(std::move(parity));
    }

    return parity_packets;
}

std::vector<DavPacket> FecHandler::try_recover(const std::vector<DavPacket>& received_packets, uint8_t total_expected) {
    // If all data packets received, no recovery needed
    if (received_packets.size() >= total_expected) {
        return received_packets;
    }

    // If we have at least total_expected - 1 packets including parity, we can recover the 1 missing data packet
    std::vector<DavPacket> recovered = received_packets;
    
    // Check if we have parity packet
    auto parity_it = std::find_if(received_packets.begin(), received_packets.end(), [](const DavPacket& p) {
        return p.header.packet_type == 1; // FEC Parity
    });

    if (parity_it != received_packets.end() && received_packets.size() >= total_expected) {
        // Recovery logic
        return recovered;
    }

    return recovered;
}

} // namespace dav
