#include "src/packetizer/frame_assembler.hpp"

namespace dav {

FrameAssembler::FrameAssembler(uint64_t frame_timeout_us)
    : frame_timeout_us_(frame_timeout_us) {
}

void FrameAssembler::reset() {
    pending_frames_.clear();
    assembled_frames_count_ = 0;
    dropped_frames_count_ = 0;
}

void FrameAssembler::prune_stale_frames(uint64_t now_us) {
    auto it = pending_frames_.begin();
    while (it != pending_frames_.end()) {
        if (now_us > it->second.creation_time_us && (now_us - it->second.creation_time_us) > frame_timeout_us_) {
            dropped_frames_count_++;
            it = pending_frames_.erase(it);
        } else {
            ++it;
        }
    }
}

std::optional<EncodedPacket> FrameAssembler::push_packet(const DavPacket& packet, uint64_t now_us) {
    prune_stale_frames(now_us);

    const uint32_t frame_id = packet.header.frame_id;
    const uint16_t frag_idx = packet.header.fragment_index;
    const uint16_t frag_tot = packet.header.fragment_total;

    auto& entry = pending_frames_[frame_id];
    if (entry.fragments_received == 0) {
        entry.frame_id = frame_id;
        entry.timestamp_us = packet.header.timestamp_us;
        entry.is_keyframe = packet.header.is_keyframe();
        entry.fragment_total = frag_tot;
        entry.creation_time_us = now_us;
    }

    if (entry.fragments.find(frag_idx) == entry.fragments.end()) {
        entry.fragments[frag_idx] = packet.payload;
        entry.fragments_received++;
    }

    // Check if frame is complete
    if (entry.fragments_received >= entry.fragment_total && entry.fragment_total > 0) {
        EncodedPacket assembled{};
        assembled.frame_index = entry.frame_id;
        assembled.timestamp_us = entry.timestamp_us;
        assembled.is_keyframe = entry.is_keyframe;
        assembled.frame_type = entry.is_keyframe ? FrameType::IDR : FrameType::P_Frame;
        assembled.pts = static_cast<uint32_t>(entry.timestamp_us / 1000);
        assembled.dts = assembled.pts;

        // Pre-calculate total size to allocate only once
        size_t total_assembled_size = 0;
        for (const auto& [_, frag_data] : entry.fragments) {
            total_assembled_size += frag_data.size();
        }
        assembled.data.reserve(total_assembled_size);

        // Concatenate fragments in strict 0..N-1 order
        for (uint16_t i = 0; i < entry.fragment_total; ++i) {
            auto frag_it = entry.fragments.find(i);
            if (frag_it != entry.fragments.end()) {
                assembled.data.insert(assembled.data.end(), frag_it->second.begin(), frag_it->second.end());
            }
        }

        pending_frames_.erase(frame_id);
        assembled_frames_count_++;
        return assembled;
    }

    return std::nullopt;
}

} // namespace dav
