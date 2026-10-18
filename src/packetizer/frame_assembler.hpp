#pragma once

#include "src/packetizer/packet.hpp"
#include "src/codec/codec_params.hpp"
#include <map>
#include <optional>
#include <vector>
#include <cstdint>

namespace dav {

struct IncompleteFrame {
    uint32_t frame_id{0};
    uint64_t timestamp_us{0};
    bool is_keyframe{false};
    uint16_t fragment_total{0};
    uint16_t fragments_received{0};
    uint64_t creation_time_us{0};
    std::map<uint16_t, Buffer> fragments;
};

class FrameAssembler {
public:
    explicit FrameAssembler(uint64_t frame_timeout_us = 200000); // 200ms timeout

    std::optional<EncodedPacket> push_packet(const DavPacket& packet, uint64_t now_us);
    void prune_stale_frames(uint64_t now_us);
    void reset();

    [[nodiscard]] size_t get_pending_frames_count() const noexcept { return pending_frames_.size(); }
    [[nodiscard]] uint64_t get_assembled_count() const noexcept { return assembled_frames_count_; }
    [[nodiscard]] uint64_t get_dropped_count() const noexcept { return dropped_frames_count_; }

private:
    uint64_t frame_timeout_us_;
    std::map<uint32_t, IncompleteFrame> pending_frames_;
    uint64_t assembled_frames_count_{0};
    uint64_t dropped_frames_count_{0};
};

} // namespace dav
