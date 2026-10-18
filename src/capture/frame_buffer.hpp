#pragma once

#include "src/capture/capturer.hpp"
#include <atomic>
#include <vector>
#include <optional>

namespace dav {

class FrameRingBuffer {
public:
    explicit FrameRingBuffer(size_t capacity = 4);
    ~FrameRingBuffer() = default;

    FrameRingBuffer(const FrameRingBuffer&) = delete;
    FrameRingBuffer& operator=(const FrameRingBuffer&) = delete;

    bool push(CapturedFrame&& frame);
    std::optional<CapturedFrame> pop();

    [[nodiscard]] size_t size() const noexcept;
    [[nodiscard]] size_t capacity() const noexcept { return capacity_; }
    [[nodiscard]] bool empty() const noexcept;
    [[nodiscard]] bool full() const noexcept;
    void clear();

private:
    const size_t capacity_;
    std::vector<CapturedFrame> buffer_;
    
    alignas(64) std::atomic<size_t> head_{0}; // Producer writes here
    alignas(64) std::atomic<size_t> tail_{0}; // Consumer reads here
};

} // namespace dav
