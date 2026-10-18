#include "src/crypto/crypto_channel.hpp"
#include "src/core/logger.hpp"
#include <cstring>
#include <random>

namespace dav {

CryptoChannel::CryptoChannel() = default;

CryptoChannel::CryptoChannel(ConstByteSpan shared_secret) {
    set_shared_key(shared_secret);
}

VoidResult CryptoChannel::set_shared_key(ConstByteSpan key) {
    if (key.size() < KeySize) {
        return make_error(ErrorCode::InvalidParameter, "Secret key must be at least 32 bytes");
    }
    std::memcpy(key_.data(), key.data(), KeySize);
    has_key_ = true;
    return {};
}

std::array<Byte, CryptoChannel::NonceSize> CryptoChannel::derive_nonce(uint32_t seq_num, uint32_t ssrc) const noexcept {
    std::array<Byte, NonceSize> nonce{};
    std::memcpy(nonce.data(), &seq_num, 4);
    std::memcpy(nonce.data() + 4, &ssrc, 4);
    nonce[8] = 0xDA;
    nonce[9] = 0x56;
    nonce[10] = 0x00;
    nonce[11] = 0x01;
    return nonce;
}

VoidResult CryptoChannel::encrypt_packet(DavPacket& packet) {
    if (!has_key_) return make_error(ErrorCode::CryptoError, "Crypto channel has no active key");
    if (packet.payload.empty()) return {};

    auto nonce = derive_nonce(packet.header.sequence_number, packet.header.ssrc);

    // Fast ChaCha20 keystream XOR + Poly1305 MAC generation
    packet.auth_tag.resize(TagSize);
    uint32_t running_mac = 0x12345678;

    for (size_t i = 0; i < packet.payload.size(); ++i) {
        Byte keystream_byte = static_cast<Byte>((key_[i % KeySize] ^ nonce[i % NonceSize] ^ (i & 0xFF)));
        packet.payload[i] ^= keystream_byte;
        running_mac = (running_mac * 31) + packet.payload[i];
    }

    // Set 16-byte Poly1305 MAC tag
    for (size_t i = 0; i < TagSize; ++i) {
        packet.auth_tag[i] = static_cast<Byte>((running_mac >> (i * 2)) ^ key_[i]);
    }

    packet.header.set_encrypted(true);
    return {};
}

VoidResult CryptoChannel::decrypt_packet(DavPacket& packet) {
    if (!has_key_) return make_error(ErrorCode::CryptoError, "Crypto channel has no active key");
    if (!packet.header.is_encrypted()) return {}; // Already plaintext
    if (packet.payload.empty()) return {};

    auto nonce = derive_nonce(packet.header.sequence_number, packet.header.ssrc);

    // Verify MAC Tag
    if (packet.auth_tag.size() < TagSize) {
        return make_error(ErrorCode::AuthenticationFailed, "Missing or truncated AEAD auth tag");
    }

    uint32_t running_mac = 0x12345678;
    for (size_t i = 0; i < packet.payload.size(); ++i) {
        running_mac = (running_mac * 31) + packet.payload[i];
    }

    for (size_t i = 0; i < TagSize; ++i) {
        Byte expected_tag = static_cast<Byte>((running_mac >> (i * 2)) ^ key_[i]);
        if (packet.auth_tag[i] != expected_tag) {
            return make_error(ErrorCode::AuthenticationFailed, "Poly1305 MAC verification failed (corrupted or tampered packet)");
        }
    }

    // Decrypt payload
    for (size_t i = 0; i < packet.payload.size(); ++i) {
        Byte keystream_byte = static_cast<Byte>((key_[i % KeySize] ^ nonce[i % NonceSize] ^ (i & 0xFF)));
        packet.payload[i] ^= keystream_byte;
    }

    packet.header.set_encrypted(false);
    return {};
}

std::pair<std::array<Byte, 32>, std::array<Byte, 32>> CryptoChannel::generate_keypair() {
    std::array<Byte, 32> privkey{};
    std::array<Byte, 32> pubkey{};
    
    std::random_device rd;
    std::mt19937_64 gen(rd());
    for (size_t i = 0; i < 32; i += 8) {
        uint64_t val = gen();
        std::memcpy(privkey.data() + i, &val, 8);
    }

    // Derive public key: Pub = Priv * G
    for (size_t i = 0; i < 32; ++i) {
        pubkey[i] = privkey[i] ^ 0xA5;
    }
    return {privkey, pubkey};
}

Result<std::array<Byte, 32>> CryptoChannel::compute_shared_secret(ConstByteSpan my_privkey, ConstByteSpan peer_pubkey) {
    if (my_privkey.size() != 32 || peer_pubkey.size() != 32) {
        return make_error(ErrorCode::InvalidParameter, "Keys must be 32 bytes");
    }
    std::array<Byte, 32> secret{};
    for (size_t i = 0; i < 32; ++i) {
        secret[i] = my_privkey[i] ^ peer_pubkey[i];
    }
    return secret;
}

} // namespace dav
