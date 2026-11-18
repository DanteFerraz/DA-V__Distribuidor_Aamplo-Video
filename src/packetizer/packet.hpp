#pragma once

#include "src/core/types.hpp"
#include <array>
#include <cstdint>
#include <cstring>

namespace dav {

// Payload Types canonicos (compartilhados bit-a-bit entre C++23 e Python)
constexpr uint8_t PT_VIDEO   = 0x00;
constexpr uint8_t PT_FEC     = 0x01;
constexpr uint8_t PT_AUDIO   = 0x02;
constexpr uint8_t PT_CONTROL = 0x03;

// Flags de cabecalho
constexpr uint8_t FLAG_KEYFRAME     = 0x01;
constexpr uint8_t FLAG_ENCRYPTED    = 0x02;
constexpr uint8_t FLAG_FEC_FLAG     = 0x04;
constexpr uint8_t FLAG_LAST_FRAG    = 0x08;
constexpr uint8_t FLAG_AEAD_CHACHA  = 0x10;
constexpr uint8_t FLAG_AUDIO_LBRR   = 0x20;
constexpr uint8_t FLAG_PIR_VIDEO    = 0x40;

constexpr uint32_t DAV_WIRE_SSRC = 0x00DA0001;

// Alinhamento canonico identico ao formato network big-endian '!BBBBIIQIIHH' (32 bytes):
// version(1), packet_type(1), flags(1), reserved(1), sequence_number(4), ssrc(4),
// timestamp_us(8), frame_id(4), payload_length(4), fragment_index(2), fragment_total(2)
#pragma pack(push, 1)
struct PacketHeader {
    uint8_t version{1};
    uint8_t packet_type{PT_VIDEO};
    uint8_t flags{0};
    uint8_t reserved{0};

    uint32_t sequence_number{0};
    uint32_t ssrc{DAV_WIRE_SSRC};
    uint64_t timestamp_us{0};
    uint32_t frame_id{0};
    uint32_t payload_length{0};
    uint16_t fragment_index{0};
    uint16_t fragment_total{1};

    static constexpr size_t HeaderSize = 32;
    static constexpr size_t MaxMtu = 1400;
    static constexpr size_t MaxPayload = 1300;

    [[nodiscard]] bool is_keyframe() const noexcept { return (flags & FLAG_KEYFRAME) != 0; }
    void set_keyframe(bool val) noexcept { if (val) flags |= FLAG_KEYFRAME; else flags &= ~FLAG_KEYFRAME; }

    [[nodiscard]] bool is_encrypted() const noexcept { return (flags & FLAG_ENCRYPTED) != 0; }
    void set_encrypted(bool val) noexcept { if (val) flags |= FLAG_ENCRYPTED; else flags &= ~FLAG_ENCRYPTED; }

    [[nodiscard]] bool is_fec() const noexcept { return (flags & FLAG_FEC_FLAG) != 0; }
    void set_fec(bool val) noexcept { if (val) flags |= FLAG_FEC_FLAG; else flags &= ~FLAG_FEC_FLAG; }

    [[nodiscard]] bool is_last_fragment() const noexcept { return (flags & FLAG_LAST_FRAG) != 0; }
    void set_last_fragment(bool val) noexcept { if (val) flags |= FLAG_LAST_FRAG; else flags &= ~FLAG_LAST_FRAG; }

    [[nodiscard]] bool is_aead() const noexcept { return (flags & FLAG_AEAD_CHACHA) != 0; }
    void set_aead(bool val) noexcept { if (val) flags |= FLAG_AEAD_CHACHA; else flags &= ~FLAG_AEAD_CHACHA; }

    [[nodiscard]] std::array<Byte, HeaderSize> to_wire_bytes() const noexcept {
        std::array<Byte, HeaderSize> b{};
        b[0] = version;
        b[1] = packet_type;
        b[2] = flags;
        b[3] = reserved;
        auto put32 = [&](size_t off, uint32_t v) {
            b[off]     = static_cast<Byte>((v >> 24) & 0xFF);
            b[off + 1] = static_cast<Byte>((v >> 16) & 0xFF);
            b[off + 2] = static_cast<Byte>((v >> 8) & 0xFF);
            b[off + 3] = static_cast<Byte>(v & 0xFF);
        };
        auto put64 = [&](size_t off, uint64_t v) {
            for (size_t i = 0; i < 8; ++i) {
                b[off + i] = static_cast<Byte>((v >> ((7 - i) * 8)) & 0xFF);
            }
        };
        auto put16 = [&](size_t off, uint16_t v) {
            b[off]     = static_cast<Byte>((v >> 8) & 0xFF);
            b[off + 1] = static_cast<Byte>(v & 0xFF);
        };
        put32(4, sequence_number);
        put32(8, ssrc);
        put64(12, timestamp_us);
        put32(20, frame_id);
        put32(24, payload_length);
        put16(28, fragment_index);
        put16(30, fragment_total);
        return b;
    }

    static bool from_wire_bytes(const Byte* data, size_t len, PacketHeader& out) noexcept {
        if (!data || len < HeaderSize) return false;
        auto get32 = [&](size_t off) -> uint32_t {
            return (static_cast<uint32_t>(data[off]) << 24) |
                   (static_cast<uint32_t>(data[off + 1]) << 16) |
                   (static_cast<uint32_t>(data[off + 2]) << 8) |
                   static_cast<uint32_t>(data[off + 3]);
        };
        auto get64 = [&](size_t off) -> uint64_t {
            uint64_t v = 0;
            for (size_t i = 0; i < 8; ++i) v = (v << 8) | data[off + i];
            return v;
        };
        auto get16 = [&](size_t off) -> uint16_t {
            return static_cast<uint16_t>((static_cast<uint16_t>(data[off]) << 8) | data[off + 1]);
        };
        out.version = data[0];
        out.packet_type = data[1];
        out.flags = data[2];
        out.reserved = data[3];
        out.sequence_number = get32(4);
        out.ssrc = get32(8);
        out.timestamp_us = get64(12);
        out.frame_id = get32(20);
        out.payload_length = get32(24);
        out.fragment_index = get16(28);
        out.fragment_total = get16(30);
        return out.version == 1 && out.fragment_total > 0 && out.fragment_index < out.fragment_total;
    }
};
#pragma pack(pop)

static_assert(sizeof(PacketHeader) == 32, "PacketHeader must be exactly 32 bytes for wire protocol");

struct DavPacket {
    PacketHeader header;
    Buffer payload;
    Buffer auth_tag; // 16 bytes for Poly1305 AEAD

    [[nodiscard]] Buffer serialize() const {
        auto hdr_wire = header.to_wire_bytes();
        Buffer out(PacketHeader::HeaderSize + payload.size() + auth_tag.size());
        std::memcpy(out.data(), hdr_wire.data(), PacketHeader::HeaderSize);
        if (!payload.empty()) {
            std::memcpy(out.data() + PacketHeader::HeaderSize, payload.data(), payload.size());
        }
        if (!auth_tag.empty()) {
            std::memcpy(out.data() + PacketHeader::HeaderSize + payload.size(), auth_tag.data(), auth_tag.size());
        }
        return out;
    }
};

} // namespace dav
