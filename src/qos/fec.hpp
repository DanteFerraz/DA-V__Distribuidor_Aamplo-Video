// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
// Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
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

    // Primitivas GF(2^8) sistematicas (Cauchy Reed-Solomon + fast-path XOR)
    static bool encode_gf256_raw(
        uint16_t k_data,
        uint8_t m_parity,
        size_t shard_len,
        const uint8_t* data_concat,
        uint8_t* out_parity_concat
    ) noexcept;

    static bool recover_gf256_raw(
        uint16_t k_data,
        uint8_t m_parity,
        size_t shard_len,
        const uint8_t* data_present,
        const uint8_t* parity_present,
        uint8_t* data_shards_inout,
        const uint8_t* parity_shards_in
    ) noexcept;

    // API orientada a DavPacket (usada por QosEngine)
    std::vector<DavPacket> generate_parity(const std::vector<DavPacket>& data_packets, uint32_t block_id);
    std::vector<DavPacket> try_recover(const std::vector<DavPacket>& received_packets, uint8_t total_expected);

    void set_overhead_ratio(uint8_t data_shards, uint8_t parity_shards);
    [[nodiscard]] double get_overhead_percentage() const noexcept;

private:
    uint8_t data_shards_;
    uint8_t parity_shards_;
};

} // namespace dav
