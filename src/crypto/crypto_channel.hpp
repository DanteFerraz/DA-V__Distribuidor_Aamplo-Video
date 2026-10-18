#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include "src/packetizer/packet.hpp"
#include <array>
#include <string_view>
#include <vector>

namespace dav {

class CryptoChannel {
public:
    static constexpr size_t KeySize = 32;       // 256-bit key
    static constexpr size_t NonceSize = 12;     // 96-bit nonce
    static constexpr size_t TagSize = 16;       // 128-bit Poly1305 MAC tag

    CryptoChannel();
    explicit CryptoChannel(ConstByteSpan shared_secret);
    ~CryptoChannel() = default;

    VoidResult set_shared_key(ConstByteSpan key);
    
    // Encrypt payload in-place or into packet
    VoidResult encrypt_packet(DavPacket& packet);
    VoidResult decrypt_packet(DavPacket& packet);

    // Key exchange (X25519)
    static std::pair<std::array<Byte, 32>, std::array<Byte, 32>> generate_keypair();
    static Result<std::array<Byte, 32>> compute_shared_secret(ConstByteSpan my_privkey, ConstByteSpan peer_pubkey);

    [[nodiscard]] bool is_ready() const noexcept { return has_key_; }

private:
    std::array<Byte, NonceSize> derive_nonce(uint32_t seq_num, uint32_t ssrc) const noexcept;

    std::array<Byte, KeySize> key_{};
    bool has_key_{false};
};

} // namespace dav
