#include "src/crypto/crypto_channel.hpp"
#include <algorithm>
#include <cstring>

namespace dav {

namespace {

inline uint32_t load32_le(const Byte* p) noexcept {
    return static_cast<uint32_t>(p[0]) |
           (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

inline void store32_le(Byte* p, uint32_t v) noexcept {
    p[0] = static_cast<Byte>(v & 0xFF);
    p[1] = static_cast<Byte>((v >> 8) & 0xFF);
    p[2] = static_cast<Byte>((v >> 16) & 0xFF);
    p[3] = static_cast<Byte>((v >> 24) & 0xFF);
}

inline void store64_le(Byte* p, uint64_t v) noexcept {
    for (int i = 0; i < 8; ++i) {
        p[i] = static_cast<Byte>((v >> (i * 8)) & 0xFF);
    }
}

inline uint32_t rotl32(uint32_t v, int c) noexcept {
    return (v << c) | (v >> (32 - c));
}

inline void quarter_round(uint32_t& a, uint32_t& b, uint32_t& c, uint32_t& d) noexcept {
    a += b; d ^= a; d = rotl32(d, 16);
    c += d; b ^= c; b = rotl32(b, 12);
    a += b; d ^= a; d = rotl32(d, 8);
    c += d; b ^= c; b = rotl32(b, 7);
}

void chacha20_block(const Byte* key32, uint32_t counter, const Byte* nonce12, Byte* out64) noexcept {
    uint32_t init[16]{
        0x61707865u, 0x3320646eu, 0x79622d32u, 0x6b206574u,
        load32_le(key32 + 0),  load32_le(key32 + 4),  load32_le(key32 + 8),  load32_le(key32 + 12),
        load32_le(key32 + 16), load32_le(key32 + 20), load32_le(key32 + 24), load32_le(key32 + 28),
        counter,
        load32_le(nonce12 + 0), load32_le(nonce12 + 4), load32_le(nonce12 + 8)
    };
    uint32_t x[16];
    std::memcpy(x, init, sizeof(init));

    for (int i = 0; i < 10; ++i) {
        quarter_round(x[0], x[4], x[8],  x[12]);
        quarter_round(x[1], x[5], x[9],  x[13]);
        quarter_round(x[2], x[6], x[10], x[14]);
        quarter_round(x[3], x[7], x[11], x[15]);
        quarter_round(x[0], x[5], x[10], x[15]);
        quarter_round(x[1], x[6], x[11], x[12]);
        quarter_round(x[2], x[7], x[8],  x[13]);
        quarter_round(x[3], x[4], x[9],  x[14]);
    }
    for (int i = 0; i < 16; ++i) {
        store32_le(out64 + i * 4, x[i] + init[i]);
    }
}

void chacha20_xor(
    const Byte* key32,
    uint32_t counter,
    const Byte* nonce12,
    const Byte* in_data,
    Byte* out_data,
    size_t len
) noexcept {
    Byte ks[64]{};
    size_t offset = 0;
    while (offset < len) {
        chacha20_block(key32, counter++, nonce12, ks);
        size_t take = std::min<size_t>(64, len - offset);
        for (size_t i = 0; i < take; ++i) {
            out_data[offset + i] = static_cast<Byte>(in_data[offset + i] ^ ks[i]);
        }
        offset += take;
    }
}

struct Poly1305State {
    uint32_t r[5]{};
    uint32_t h[5]{};
    uint32_t pad[4]{};
    Byte buf[16]{};
    size_t leftover{0};

    explicit Poly1305State(const Byte* otk32) noexcept {
        Byte clamped[16];
        std::memcpy(clamped, otk32, 16);
        clamped[3] &= 15;  clamped[7] &= 15;  clamped[11] &= 15; clamped[15] &= 15;
        clamped[4] &= 252; clamped[8] &= 252; clamped[12] &= 252;

        r[0] = (load32_le(clamped + 0)) & 0x3FFFFFFu;
        r[1] = (load32_le(clamped + 3) >> 2) & 0x3FFFFFFu;
        r[2] = (load32_le(clamped + 6) >> 4) & 0x3FFFFFFu;
        r[3] = (load32_le(clamped + 9) >> 6) & 0x3FFFFFFu;
        r[4] = (load32_le(clamped + 12) >> 8) & 0x3FFFFFFu;

        pad[0] = load32_le(otk32 + 16);
        pad[1] = load32_le(otk32 + 20);
        pad[2] = load32_le(otk32 + 24);
        pad[3] = load32_le(otk32 + 28);
    }

    void blocks(const Byte* m, size_t len, bool is_final = false) noexcept {
        const uint32_t hibit = is_final ? 0u : (1u << 24);
        uint32_t r0 = r[0], r1 = r[1], r2 = r[2], r3 = r[3], r4 = r[4];
        uint32_t s1 = r1 * 5u, s2 = r2 * 5u, s3 = r3 * 5u, s4 = r4 * 5u;
        uint32_t h0 = h[0], h1 = h[1], h2 = h[2], h3 = h[3], h4 = h[4];

        while (len >= 16) {
            h0 += (load32_le(m + 0)) & 0x3FFFFFFu;
            h1 += (load32_le(m + 3) >> 2) & 0x3FFFFFFu;
            h2 += (load32_le(m + 6) >> 4) & 0x3FFFFFFu;
            h3 += (load32_le(m + 9) >> 6) & 0x3FFFFFFu;
            h4 += ((load32_le(m + 12) >> 8) & 0x3FFFFFFu) | hibit;

            uint64_t d0 = uint64_t(h0) * r0 + uint64_t(h1) * s4 + uint64_t(h2) * s3 + uint64_t(h3) * s2 + uint64_t(h4) * s1;
            uint64_t d1 = uint64_t(h0) * r1 + uint64_t(h1) * r0 + uint64_t(h2) * s4 + uint64_t(h3) * s3 + uint64_t(h4) * s2;
            uint64_t d2 = uint64_t(h0) * r2 + uint64_t(h1) * r1 + uint64_t(h2) * r0 + uint64_t(h3) * s4 + uint64_t(h4) * s3;
            uint64_t d3 = uint64_t(h0) * r3 + uint64_t(h1) * r2 + uint64_t(h2) * r1 + uint64_t(h3) * r0 + uint64_t(h4) * s4;
            uint64_t d4 = uint64_t(h0) * r4 + uint64_t(h1) * r3 + uint64_t(h2) * r2 + uint64_t(h3) * r1 + uint64_t(h4) * r0;

            uint32_t c;
            c = static_cast<uint32_t>(d0 >> 26); h0 = static_cast<uint32_t>(d0) & 0x3FFFFFFu; d1 += c;
            c = static_cast<uint32_t>(d1 >> 26); h1 = static_cast<uint32_t>(d1) & 0x3FFFFFFu; d2 += c;
            c = static_cast<uint32_t>(d2 >> 26); h2 = static_cast<uint32_t>(d2) & 0x3FFFFFFu; d3 += c;
            c = static_cast<uint32_t>(d3 >> 26); h3 = static_cast<uint32_t>(d3) & 0x3FFFFFFu; d4 += c;
            c = static_cast<uint32_t>(d4 >> 26); h4 = static_cast<uint32_t>(d4) & 0x3FFFFFFu; h0 += c * 5u;
            c = h0 >> 26; h0 &= 0x3FFFFFFu; h1 += c;

            m += 16;
            len -= 16;
        }
        h[0] = h0; h[1] = h1; h[2] = h2; h[3] = h3; h[4] = h4;
    }

    void update(const Byte* m, size_t bytes) noexcept {
        if (bytes == 0 || !m) return;
        if (leftover > 0) {
            size_t want = std::min(16 - leftover, bytes);
            std::memcpy(buf + leftover, m, want);
            bytes -= want;
            m += want;
            leftover += want;
            if (leftover < 16) return;
            blocks(buf, 16, false);
            leftover = 0;
        }
        if (bytes >= 16) {
            size_t full = bytes & ~size_t(15);
            blocks(m, full, false);
            m += full;
            bytes -= full;
        }
        if (bytes > 0) {
            std::memcpy(buf, m, bytes);
            leftover = bytes;
        }
    }

    void pad16(size_t len) noexcept {
        size_t rem = len % 16;
        if (rem != 0) {
            Byte zeros[16]{};
            update(zeros, 16 - rem);
        }
    }

    void finish(Byte* mac16) noexcept {
        if (leftover > 0) {
            buf[leftover] = 1;
            for (size_t i = leftover + 1; i < 16; ++i) buf[i] = 0;
            blocks(buf, 16, true);
        }

        uint32_t h0 = h[0], h1 = h[1], h2 = h[2], h3 = h[3], h4 = h[4];
        uint32_t c;
        c = h1 >> 26; h1 &= 0x3FFFFFFu; h2 += c;
        c = h2 >> 26; h2 &= 0x3FFFFFFu; h3 += c;
        c = h3 >> 26; h3 &= 0x3FFFFFFu; h4 += c;
        c = h4 >> 26; h4 &= 0x3FFFFFFu; h0 += c * 5u;
        c = h0 >> 26; h0 &= 0x3FFFFFFu; h1 += c;

        uint32_t g0 = h0 + 5u; c = g0 >> 26; g0 &= 0x3FFFFFFu;
        uint32_t g1 = h1 + c;  c = g1 >> 26; g1 &= 0x3FFFFFFu;
        uint32_t g2 = h2 + c;  c = g2 >> 26; g2 &= 0x3FFFFFFu;
        uint32_t g3 = h3 + c;  c = g3 >> 26; g3 &= 0x3FFFFFFu;
        uint32_t g4 = h4 + c - (1u << 26);

        uint32_t mask = (g4 >> 31) - 1u;
        g0 &= mask; g1 &= mask; g2 &= mask; g3 &= mask; g4 &= mask;
        mask = ~mask;
        h0 = (h0 & mask) | g0;
        h1 = (h1 & mask) | g1;
        h2 = (h2 & mask) | g2;
        h3 = (h3 & mask) | g3;
        h4 = (h4 & mask) | g4;

        uint64_t f0 = ((h0) | (h1 << 26)) + uint64_t(pad[0]);
        uint64_t f1 = ((h1 >> 6) | (h2 << 20)) + uint64_t(pad[1]) + (f0 >> 32);
        uint64_t f2 = ((h2 >> 12) | (h3 << 14)) + uint64_t(pad[2]) + (f1 >> 32);
        uint64_t f3 = ((h3 >> 18) | (h4 << 8)) + uint64_t(pad[3]) + (f2 >> 32);

        store32_le(mac16 + 0,  static_cast<uint32_t>(f0));
        store32_le(mac16 + 4,  static_cast<uint32_t>(f1));
        store32_le(mac16 + 8,  static_cast<uint32_t>(f2));
        store32_le(mac16 + 12, static_cast<uint32_t>(f3));
    }
};

} // namespace

CryptoChannel::CryptoChannel() = default;

CryptoChannel::CryptoChannel(ConstByteSpan shared_secret) {
    set_shared_key(shared_secret);
}

CryptoChannel::CryptoChannel(ConstByteSpan shared_secret, ConstByteSpan salt96) {
    set_shared_key(shared_secret);
    set_nonce_salt(salt96);
}

VoidResult CryptoChannel::set_shared_key(ConstByteSpan key) {
    if (key.size() < KeySize) {
        return make_error(ErrorCode::InvalidParameter, "Secret key must be at least 32 bytes");
    }
    std::memcpy(key_.data(), key.data(), KeySize);
    has_key_ = true;
    return {};
}

void CryptoChannel::set_nonce_salt(ConstByteSpan salt96) {
    if (salt96.size() >= NonceSize) {
        std::memcpy(salt_.data(), salt96.data(), NonceSize);
    }
}

std::array<Byte, CryptoChannel::NonceSize> CryptoChannel::derive_nonce(
    uint32_t ssrc, uint32_t frame_id, uint32_t seq_num
) const noexcept {
    std::array<Byte, NonceSize> n = salt_;
    auto xor32_be = [&](size_t off, uint32_t v) {
        n[off]     ^= static_cast<Byte>((v >> 24) & 0xFF);
        n[off + 1] ^= static_cast<Byte>((v >> 16) & 0xFF);
        n[off + 2] ^= static_cast<Byte>((v >> 8) & 0xFF);
        n[off + 3] ^= static_cast<Byte>(v & 0xFF);
    };
    xor32_be(0, ssrc);
    xor32_be(4, frame_id);
    xor32_be(8, seq_num);
    return n;
}

bool CryptoChannel::seal_aead_raw(
    const Byte* key32,
    const Byte* nonce12,
    const Byte* aad,
    size_t aad_len,
    const Byte* plaintext,
    size_t pt_len,
    Byte* out_ciphertext,
    Byte* out_tag16
) noexcept {
    if (!key32 || !nonce12 || !out_tag16) return false;
    if (pt_len > 0 && (!plaintext || !out_ciphertext)) return false;

    Byte otk_block[64]{};
    chacha20_block(key32, 0u, nonce12, otk_block);

    if (pt_len > 0) {
        chacha20_xor(key32, 1u, nonce12, plaintext, out_ciphertext, pt_len);
    }

    Poly1305State poly(otk_block);
    if (aad && aad_len > 0) {
        poly.update(aad, aad_len);
        poly.pad16(aad_len);
    }
    if (pt_len > 0) {
        poly.update(out_ciphertext, pt_len);
        poly.pad16(pt_len);
    }
    Byte lens[16]{};
    store64_le(lens, static_cast<uint64_t>(aad_len));
    store64_le(lens + 8, static_cast<uint64_t>(pt_len));
    poly.update(lens, 16);
    poly.finish(out_tag16);
    return true;
}

bool CryptoChannel::open_aead_raw(
    const Byte* key32,
    const Byte* nonce12,
    const Byte* aad,
    size_t aad_len,
    const Byte* ciphertext,
    size_t ct_len,
    const Byte* tag16,
    Byte* out_plaintext
) noexcept {
    if (!key32 || !nonce12 || !tag16) return false;
    if (ct_len > 0 && (!ciphertext || !out_plaintext)) return false;

    Byte otk_block[64]{};
    chacha20_block(key32, 0u, nonce12, otk_block);

    Poly1305State poly(otk_block);
    if (aad && aad_len > 0) {
        poly.update(aad, aad_len);
        poly.pad16(aad_len);
    }
    if (ct_len > 0) {
        poly.update(ciphertext, ct_len);
        poly.pad16(ct_len);
    }
    Byte lens[16]{};
    store64_le(lens, static_cast<uint64_t>(aad_len));
    store64_le(lens + 8, static_cast<uint64_t>(ct_len));
    poly.update(lens, 16);

    Byte computed_tag[16]{};
    poly.finish(computed_tag);

    uint8_t diff = 0;
    for (size_t i = 0; i < 16; ++i) {
        diff |= static_cast<uint8_t>(computed_tag[i] ^ tag16[i]);
    }
    if (diff != 0) {
        return false;
    }

    if (ct_len > 0) {
        chacha20_xor(key32, 1u, nonce12, ciphertext, out_plaintext, ct_len);
    }
    return true;
}

VoidResult CryptoChannel::encrypt_packet(DavPacket& packet) {
    if (!has_key_) return make_error(ErrorCode::CryptoError, "Crypto channel has no active key");
    packet.header.set_encrypted(true);
    packet.header.set_aead(true);
    packet.header.payload_length = static_cast<uint32_t>(packet.payload.size());
    packet.auth_tag.resize(TagSize);

    auto aad = packet.header.to_wire_bytes();
    uint32_t domain_ssrc = packet.header.ssrc ^ (static_cast<uint32_t>(packet.header.packet_type) << 24);
    auto nonce = derive_nonce(domain_ssrc, packet.header.frame_id, packet.header.sequence_number);
    Buffer ciphertext(packet.payload.size());
    if (!seal_aead_raw(
            key_.data(), nonce.data(), aad.data(), aad.size(),
            packet.payload.data(), packet.payload.size(),
            ciphertext.data(), packet.auth_tag.data()
        )) {
        return make_error(ErrorCode::CryptoError, "AEAD ChaCha20-Poly1305 seal failed");
    }
    packet.payload = std::move(ciphertext);
    return {};
}

VoidResult CryptoChannel::decrypt_packet(DavPacket& packet) {
    if (!has_key_) return make_error(ErrorCode::CryptoError, "Crypto channel has no active key");
    if (!packet.header.is_encrypted()) return {};
    if (packet.auth_tag.size() < TagSize) {
        return make_error(ErrorCode::AuthenticationFailed, "Missing or truncated AEAD auth tag");
    }

    auto aad = packet.header.to_wire_bytes();
    uint32_t domain_ssrc = packet.header.ssrc ^ (static_cast<uint32_t>(packet.header.packet_type) << 24);
    auto nonce = derive_nonce(domain_ssrc, packet.header.frame_id, packet.header.sequence_number);
    Buffer plaintext(packet.payload.size());
    if (!open_aead_raw(
            key_.data(), nonce.data(), aad.data(), aad.size(),
            packet.payload.data(), packet.payload.size(),
            packet.auth_tag.data(), plaintext.data()
        )) {
        return make_error(ErrorCode::AuthenticationFailed, "ChaCha20-Poly1305 MAC verification failed");
    }
    packet.payload = std::move(plaintext);
    packet.header.set_encrypted(false);
    return {};
}

} // namespace dav
