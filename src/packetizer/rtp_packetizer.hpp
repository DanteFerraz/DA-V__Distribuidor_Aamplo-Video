#pragma once

#include "src/packetizer/packet.hpp"
#include "src/codec/codec_params.hpp"
#include "src/core/result.hpp"
#include <vector>

namespace dav {

class RtpPacketizer {
public:
    explicit RtpPacketizer(uint32_t ssrc = 0xDA0001, size_t mtu = 1400);

    std::vector<DavPacket> packetize(const EncodedPacket& frame);

    void set_ssrc(uint32_t ssrc) noexcept { ssrc_ = ssrc; }
    [[nodiscard]] uint32_t get_ssrc() const noexcept { return ssrc_; }
    [[nodiscard]] uint32_t get_next_sequence_number() const noexcept { return sequence_number_; }

private:
    uint32_t ssrc_;
    size_t mtu_;
    size_t max_payload_per_packet_;
    uint32_t sequence_number_{0};
};

} // namespace dav
