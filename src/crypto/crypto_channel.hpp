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
    static constexpr size_t KeySize = 32;
    static constexpr size_t NonceSize = 12;
    static constexpr size_t TagSize = 16;

    CryptoChannel();
    explicit CryptoChannel(ConstByteSpan shared_secret);
    explicit CryptoChannel(ConstByteSpan shared_secret, ConstByteSpan salt96);
    ~CryptoChannel() = default;

    VoidResult set_shared_key(ConstByteSpan key);
    void set_nonce_salt(ConstByteSpan salt96);

    // Primitivas RFC 8439 ChaCha20-Poly1305 AEAD portaveis (zero dependencias externas)
    static bool seal_aead_raw(
        const Byte* key32,
        const Byte* nonce12,
        const Byte* aad,
        size_t aad_len,
        const Byte* plaintext,
        size_t pt_len,
        Byte* out_ciphertext,
        Byte* out_tag16
    ) noexcept;

    static bool open_aead_raw(
        const Byte* key32,
        const Byte* nonce12,
        const Byte* aad,
        size_t aad_len,
        const Byte* ciphertext,
        size_t ct_len,
        const Byte* tag16,
        Byte* out_plaintext
    ) noexcept;

    VoidResult encrypt_packet(DavPacket& packet);
    VoidResult decrypt_packet(DavPacket& packet);

    [[nodiscard]] bool is_ready() const noexcept { return has_key_; }

private:
    std::array<Byte, NonceSize> derive_nonce(uint32_t ssrc, uint32_t frame_id, uint32_t seq_num) const noexcept;

    std::array<Byte, KeySize> key_{};
    std::array<Byte, NonceSize> salt_{};
    bool has_key_{false};
};

} // namespace dav
