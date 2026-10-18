#pragma once

#include "src/core/types.hpp"
#include <cstdint>
#include <cstring>

namespace dav {

#pragma pack(push, 1)
struct PacketHeader {
    uint8_t version{1};
    uint8_t packet_type{0}; // 0 = Video Frame Fragment, 1 = FEC Parity, 2 = Control/NACK, 3 = Handshake
    uint8_t flags{0};       // Bit 0: Is Keyframe, Bit 1: Is Encrypted, Bit 2: Has FEC, Bit 3: Last Fragment
    uint8_t reserved{0};
    
    uint32_t sequence_number{0};
    uint64_t timestamp_us{0};
    uint32_t ssrc{0};
    uint32_t frame_id{0};
    uint16_t fragment_index{0};
    uint16_t fragment_total{1};
    uint32_t payload_length{0};

    static constexpr size_t HeaderSize = 32;
    static constexpr size_t MaxMtu = 1400;
    static constexpr size_t MaxPayload = MaxMtu - HeaderSize; // 1368 bytes

    [[nodiscard]] bool is_keyframe() const noexcept { return (flags & 0x01) != 0; }
    void set_keyframe(bool val) noexcept { if (val) flags |= 0x01; else flags &= ~0x01; }

    [[nodiscard]] bool is_encrypted() const noexcept { return (flags & 0x02) != 0; }
    void set_encrypted(bool val) noexcept { if (val) flags |= 0x02; else flags &= ~0x02; }

    [[nodiscard]] bool is_fec() const noexcept { return (flags & 0x04) != 0; }
    void set_fec(bool val) noexcept { if (val) flags |= 0x04; else flags &= ~0x04; }

    [[nodiscard]] bool is_last_fragment() const noexcept { return (flags & 0x08) != 0; }
    void set_last_fragment(bool val) noexcept { if (val) flags |= 0x08; else flags &= ~0x08; }
};
#pragma pack(pop)

static_assert(sizeof(PacketHeader) == 32, "PacketHeader must be exactly 32 bytes for wire protocol");

struct DavPacket {
    PacketHeader header;
    Buffer payload;
    Buffer auth_tag; // 16 bytes for Poly1305 AEAD

    [[nodiscard]] Buffer serialize() const {
        Buffer out(sizeof(PacketHeader) + payload.size() + auth_tag.size());
        std::memcpy(out.data(), &header, sizeof(PacketHeader));
        if (!payload.empty()) {
            std::memcpy(out.data() + sizeof(PacketHeader), payload.data(), payload.size());
        }
        if (!auth_tag.empty()) {
            std::memcpy(out.data() + sizeof(PacketHeader) + payload.size(), auth_tag.data(), auth_tag.size());
        }
        return out;
    }
};

} // namespace dav
