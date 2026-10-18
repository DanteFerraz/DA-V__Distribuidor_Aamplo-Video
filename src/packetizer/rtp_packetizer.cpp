#include "src/packetizer/rtp_packetizer.hpp"
#include <algorithm>

namespace dav {

RtpPacketizer::RtpPacketizer(uint32_t ssrc, size_t mtu)
    : ssrc_(ssrc),
      mtu_(mtu),
      max_payload_per_packet_(mtu > sizeof(PacketHeader) + 16 ? mtu - sizeof(PacketHeader) - 16 : 1300) {
}

std::vector<DavPacket> RtpPacketizer::packetize(const EncodedPacket& frame) {
    std::vector<DavPacket> packets;
    if (frame.data.empty()) return packets;

    const size_t total_size = frame.data.size();
    const uint16_t fragment_count = static_cast<uint16_t>((total_size + max_payload_per_packet_ - 1) / max_payload_per_packet_);
    packets.reserve(fragment_count);

    size_t offset = 0;
    for (uint16_t i = 0; i < fragment_count; ++i) {
        size_t current_chunk = std::min(max_payload_per_packet_, total_size - offset);

        DavPacket packet{};
        packet.header.version = 1;
        packet.header.packet_type = 0; // Video
        packet.header.sequence_number = ++sequence_number_;
        packet.header.timestamp_us = frame.timestamp_us;
        packet.header.ssrc = ssrc_;
        packet.header.frame_id = frame.frame_index;
        packet.header.fragment_index = i;
        packet.header.fragment_total = fragment_count;
        packet.header.payload_length = static_cast<uint32_t>(current_chunk);

        packet.header.set_keyframe(frame.is_keyframe);
        packet.header.set_last_fragment(i == fragment_count - 1);

        packet.payload.assign(frame.data.begin() + offset, frame.data.begin() + offset + current_chunk);

        packets.push_back(std::move(packet));
        offset += current_chunk;
    }

    return packets;
}

} // namespace dav
