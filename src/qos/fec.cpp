// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
// Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
#include "src/qos/fec.hpp"
#include <algorithm>
#include <array>
#include <cstring>
#include <map>
#include <utility>

namespace dav {

namespace {

struct Gf256Tables {
    std::array<uint8_t, 512> exp{};
    std::array<uint8_t, 256> log{};
    std::array<uint8_t, 256> inv{};
    std::array<uint8_t, 256 * 256> mul{};

    Gf256Tables() noexcept {
        uint16_t x = 1;
        for (int i = 0; i < 255; ++i) {
            exp[i] = static_cast<uint8_t>(x);
            log[x] = static_cast<uint8_t>(i);
            x <<= 1;
            if (x & 0x100) {
                x ^= 0x11D;
            }
        }
        for (int i = 255; i < 512; ++i) {
            exp[i] = exp[i - 255];
        }
        for (int a = 1; a < 256; ++a) {
            int la = log[a];
            inv[a] = exp[255 - la];
            for (int b = 1; b < 256; ++b) {
                mul[a * 256 + b] = exp[(la + log[b]) % 255];
            }
        }
    }
};

inline const Gf256Tables& gf_tables() noexcept {
    static const Gf256Tables tables;
    return tables;
}

inline uint8_t gf_mul(uint8_t a, uint8_t b) noexcept {
    return gf_tables().mul[static_cast<size_t>(a) * 256 + b];
}

inline uint8_t cauchy_coef(uint16_t parity_idx, uint16_t data_idx, uint16_t k_data) noexcept {
    uint16_t x_i = k_data + parity_idx;
    uint16_t y_j = data_idx;
    return gf_tables().inv[x_i ^ y_j];
}

bool invert_gf_matrix(std::vector<std::vector<uint8_t>>& mat, std::vector<std::vector<uint8_t>>& inv_out) {
    const size_t n = mat.size();
    inv_out.assign(n, std::vector<uint8_t>(n, 0));
    for (size_t i = 0; i < n; ++i) {
        inv_out[i][i] = 1;
    }

    for (size_t col = 0; col < n; ++col) {
        size_t pivot = n;
        for (size_t r = col; r < n; ++r) {
            if (mat[r][col] != 0) {
                pivot = r;
                break;
            }
        }
        if (pivot == n) return false;

        if (pivot != col) {
            std::swap(mat[col], mat[pivot]);
            std::swap(inv_out[col], inv_out[pivot]);
        }

        uint8_t inv_piv = gf_tables().inv[mat[col][col]];
        if (inv_piv != 1) {
            for (size_t c = 0; c < n; ++c) {
                mat[col][c] = gf_mul(mat[col][c], inv_piv);
                inv_out[col][c] = gf_mul(inv_out[col][c], inv_piv);
            }
        }

        for (size_t r = 0; r < n; ++r) {
            if (r != col && mat[r][col] != 0) {
                uint8_t factor = mat[r][col];
                for (size_t c = 0; c < n; ++c) {
                    mat[r][c] ^= gf_mul(factor, mat[col][c]);
                    inv_out[r][c] ^= gf_mul(factor, inv_out[col][c]);
                }
            }
        }
    }
    return true;
}

} // namespace

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

bool FecHandler::encode_gf256_raw(
    uint16_t k_data,
    uint8_t m_parity,
    size_t shard_len,
    const uint8_t* data_concat,
    uint8_t* out_parity_concat
) noexcept {
    if (k_data == 0 || m_parity == 0 || shard_len == 0 || !data_concat || !out_parity_concat) {
        return false;
    }
    if (static_cast<size_t>(k_data) + m_parity > 255) {
        return false;
    }

    if (m_parity == 1) {
        std::memcpy(out_parity_concat, data_concat, shard_len);
        for (uint16_t j = 1; j < k_data; ++j) {
            const uint8_t* src = data_concat + static_cast<size_t>(j) * shard_len;
            for (size_t b = 0; b < shard_len; ++b) {
                out_parity_concat[b] ^= src[b];
            }
        }
        return true;
    }

    for (uint8_t p = 0; p < m_parity; ++p) {
        uint8_t* dst = out_parity_concat + static_cast<size_t>(p) * shard_len;
        std::memset(dst, 0, shard_len);
        for (uint16_t j = 0; j < k_data; ++j) {
            uint8_t c = cauchy_coef(p, j, k_data);
            const uint8_t* src = data_concat + static_cast<size_t>(j) * shard_len;
            if (c == 1) {
                for (size_t b = 0; b < shard_len; ++b) dst[b] ^= src[b];
            } else if (c != 0) {
                const uint8_t* mul_row = &gf_tables().mul[static_cast<size_t>(c) * 256];
                for (size_t b = 0; b < shard_len; ++b) dst[b] ^= mul_row[src[b]];
            }
        }
    }
    return true;
}

bool FecHandler::recover_gf256_raw(
    uint16_t k_data,
    uint8_t m_parity,
    size_t shard_len,
    const uint8_t* data_present,
    const uint8_t* parity_present,
    uint8_t* data_shards_inout,
    const uint8_t* parity_shards_in
) noexcept {
    if (k_data == 0 || shard_len == 0 || !data_present || !data_shards_inout) {
        return false;
    }

    std::vector<uint16_t> missing;
    missing.reserve(m_parity);
    for (uint16_t j = 0; j < k_data; ++j) {
        if (!data_present[j]) missing.push_back(j);
    }
    if (missing.empty()) return true;
    if (!parity_present || !parity_shards_in) return false;

    std::vector<uint8_t> avail_parity;
    avail_parity.reserve(missing.size());
    for (uint8_t p = 0; p < m_parity; ++p) {
        if (parity_present[p]) {
            avail_parity.push_back(p);
            if (avail_parity.size() == missing.size()) break;
        }
    }
    const size_t r = missing.size();
    if (avail_parity.size() < r) return false;

    // Fast-path XOR / perda unitaria
    if (r == 1 && m_parity == 1 && avail_parity[0] == 0) {
        uint8_t* out_shard = data_shards_inout + static_cast<size_t>(missing[0]) * shard_len;
        std::memcpy(out_shard, parity_shards_in, shard_len);
        for (uint16_t j = 0; j < k_data; ++j) {
            if (j == missing[0]) continue;
            const uint8_t* src = data_shards_inout + static_cast<size_t>(j) * shard_len;
            for (size_t b = 0; b < shard_len; ++b) out_shard[b] ^= src[b];
        }
        return true;
    }

    // Elimina contribuicao dos fragmentos de dados presentes e resolve r x r em GF(2^8)
    std::vector<std::vector<uint8_t>> rhs(r, std::vector<uint8_t>(shard_len, 0));
    std::vector<std::vector<uint8_t>> sub_mat(r, std::vector<uint8_t>(r, 0));

    for (size_t row = 0; row < r; ++row) {
        uint8_t p_idx = avail_parity[row];
        const uint8_t* p_bytes = parity_shards_in + static_cast<size_t>(p_idx) * shard_len;
        std::memcpy(rhs[row].data(), p_bytes, shard_len);

        for (uint16_t j = 0; j < k_data; ++j) {
            if (!data_present[j]) continue;
            uint8_t c = cauchy_coef(p_idx, j, k_data);
            if (c == 0) continue;
            const uint8_t* src = data_shards_inout + static_cast<size_t>(j) * shard_len;
            if (c == 1) {
                for (size_t b = 0; b < shard_len; ++b) rhs[row][b] ^= src[b];
            } else {
                const uint8_t* mul_row = &gf_tables().mul[static_cast<size_t>(c) * 256];
                for (size_t b = 0; b < shard_len; ++b) rhs[row][b] ^= mul_row[src[b]];
            }
        }

        for (size_t col = 0; col < r; ++col) {
            sub_mat[row][col] = cauchy_coef(p_idx, missing[col], k_data);
        }
    }

    std::vector<std::vector<uint8_t>> inv_mat;
    if (!invert_gf_matrix(sub_mat, inv_mat)) {
        return false;
    }

    for (size_t out_row = 0; out_row < r; ++out_row) {
        uint8_t* dst = data_shards_inout + static_cast<size_t>(missing[out_row]) * shard_len;
        std::memset(dst, 0, shard_len);
        for (size_t k = 0; k < r; ++k) {
            uint8_t c = inv_mat[out_row][k];
            if (c == 1) {
                for (size_t b = 0; b < shard_len; ++b) dst[b] ^= rhs[k][b];
            } else if (c != 0) {
                const uint8_t* mul_row = &gf_tables().mul[static_cast<size_t>(c) * 256];
                for (size_t b = 0; b < shard_len; ++b) dst[b] ^= mul_row[rhs[k][b]];
            }
        }
    }
    return true;
}

std::vector<DavPacket> FecHandler::generate_parity(const std::vector<DavPacket>& data_packets, uint32_t block_id) {
    std::vector<DavPacket> parity_packets;
    if (data_packets.size() <= 1 || parity_shards_ == 0) return parity_packets;

    const uint16_t k_data = static_cast<uint16_t>(data_packets.size());
    size_t max_payload = 0;
    for (const auto& p : data_packets) {
        max_payload = std::max(max_payload, p.payload.size());
    }
    if (max_payload == 0) return parity_packets;

    std::vector<uint8_t> flat_data(static_cast<size_t>(k_data) * max_payload, 0);
    for (uint16_t j = 0; j < k_data; ++j) {
        if (!data_packets[j].payload.empty()) {
            std::memcpy(
                flat_data.data() + static_cast<size_t>(j) * max_payload,
                data_packets[j].payload.data(),
                data_packets[j].payload.size()
            );
        }
    }

    std::vector<uint8_t> flat_parity(static_cast<size_t>(parity_shards_) * max_payload, 0);
    if (!encode_gf256_raw(k_data, parity_shards_, max_payload, flat_data.data(), flat_parity.data())) {
        return parity_packets;
    }

    for (uint8_t p_idx = 0; p_idx < parity_shards_; ++p_idx) {
        DavPacket parity{};
        parity.header.version = 1;
        parity.header.packet_type = PT_FEC;
        parity.header.set_fec(true);
        parity.header.sequence_number = 0xFEC00000 | (block_id << 4) | p_idx;
        parity.header.ssrc = DAV_WIRE_SSRC;
        parity.header.frame_id = block_id;
        parity.header.fragment_index = p_idx;
        parity.header.fragment_total = parity_shards_;
        parity.header.payload_length = static_cast<uint32_t>(max_payload);

        parity.payload.assign(
            flat_parity.begin() + static_cast<size_t>(p_idx) * max_payload,
            flat_parity.begin() + static_cast<size_t>(p_idx + 1) * max_payload
        );
        parity_packets.push_back(std::move(parity));
    }
    return parity_packets;
}

std::vector<DavPacket> FecHandler::try_recover(const std::vector<DavPacket>& received_packets, uint8_t total_expected) {
    if (total_expected == 0 || received_packets.empty()) return received_packets;

    std::map<uint16_t, const DavPacket*> data_map;
    std::map<uint8_t, const DavPacket*> parity_map;
    size_t max_payload = 0;
    uint32_t frame_id = received_packets.front().header.frame_id;

    for (const auto& pkt : received_packets) {
        max_payload = std::max(max_payload, pkt.payload.size());
        if (pkt.header.packet_type == PT_FEC) {
            parity_map[static_cast<uint8_t>(pkt.header.fragment_index)] = &pkt;
        } else if (pkt.header.fragment_index < total_expected) {
            data_map[pkt.header.fragment_index] = &pkt;
        }
    }

    if (data_map.size() >= total_expected || max_payload == 0) {
        return received_packets;
    }

    uint8_t max_p = parity_shards_;
    for (const auto& kv : parity_map) {
        max_p = std::max<uint8_t>(max_p, static_cast<uint8_t>(kv.first + 1));
    }

    std::vector<uint8_t> d_pres(total_expected, 0);
    std::vector<uint8_t> p_pres(max_p, 0);
    std::vector<uint8_t> d_flat(static_cast<size_t>(total_expected) * max_payload, 0);
    std::vector<uint8_t> p_flat(static_cast<size_t>(max_p) * max_payload, 0);

    for (const auto& [idx, ptr] : data_map) {
        d_pres[idx] = 1;
        if (!ptr->payload.empty()) {
            std::memcpy(d_flat.data() + static_cast<size_t>(idx) * max_payload, ptr->payload.data(), ptr->payload.size());
        }
    }
    for (const auto& [p_idx, ptr] : parity_map) {
        p_pres[p_idx] = 1;
        if (!ptr->payload.empty()) {
            std::memcpy(p_flat.data() + static_cast<size_t>(p_idx) * max_payload, ptr->payload.data(), ptr->payload.size());
        }
    }

    if (!recover_gf256_raw(total_expected, max_p, max_payload, d_pres.data(), p_pres.data(), d_flat.data(), p_flat.data())) {
        return received_packets;
    }

    std::vector<DavPacket> out;
    out.reserve(total_expected);
    for (uint16_t j = 0; j < total_expected; ++j) {
        auto it = data_map.find(j);
        if (it != data_map.end()) {
            out.push_back(*it->second);
        } else {
            DavPacket rec{};
            rec.header.version = 1;
            rec.header.packet_type = PT_VIDEO;
            rec.header.ssrc = DAV_WIRE_SSRC;
            rec.header.frame_id = frame_id;
            rec.header.fragment_index = j;
            rec.header.fragment_total = total_expected;
            rec.header.payload_length = static_cast<uint32_t>(max_payload);
            rec.payload.assign(
                d_flat.begin() + static_cast<size_t>(j) * max_payload,
                d_flat.begin() + static_cast<size_t>(j + 1) * max_payload
            );
            out.push_back(std::move(rec));
        }
    }
    return out;
}

} // namespace dav
