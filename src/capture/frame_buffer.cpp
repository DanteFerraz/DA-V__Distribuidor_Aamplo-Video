#include "src/capture/frame_buffer.hpp"

namespace dav {

FrameRingBuffer::FrameRingBuffer(size_t capacity)
    : capacity_(capacity > 0 ? capacity + 1 : 4), // +1 for full/empty distinction in lock-free ring
      buffer_(capacity_) {
}

bool FrameRingBuffer::push(CapturedFrame&& frame) {
    const size_t current_head = head_.load(std::memory_order_relaxed);
    const size_t next_head = (current_head + 1) % capacity_;

    if (next_head == tail_.load(std::memory_order_acquire)) {
        // Buffer full: drop oldest frame (tail++) to maintain lowest latency for live video stream
        size_t current_tail = tail_.load(std::memory_order_relaxed);
        tail_.store((current_tail + 1) % capacity_, std::memory_order_release);
    }

    buffer_[current_head] = std::move(frame);
    head_.store(next_head, std::memory_order_release);
    return true;
}

std::optional<CapturedFrame> FrameRingBuffer::pop() {
    const size_t current_tail = tail_.load(std::memory_order_relaxed);

    if (current_tail == head_.load(std::memory_order_acquire)) {
        return std::nullopt; // Buffer empty
    }

    CapturedFrame frame = std::move(buffer_[current_tail]);
    tail_.store((current_tail + 1) % capacity_, std::memory_order_release);
    return frame;
}

size_t FrameRingBuffer::size() const noexcept {
    const size_t head = head_.load(std::memory_order_relaxed);
    const size_t tail = tail_.load(std::memory_order_relaxed);
    if (head >= tail) {
        return head - tail;
    }
    return capacity_ - (tail - head);
}

bool FrameRingBuffer::empty() const noexcept {
    return head_.load(std::memory_order_relaxed) == tail_.load(std::memory_order_relaxed);
}

bool FrameRingBuffer::full() const noexcept {
    return ((head_.load(std::memory_order_relaxed) + 1) % capacity_) == tail_.load(std::memory_order_relaxed);
}

void FrameRingBuffer::clear() {
    tail_.store(head_.load(std::memory_order_relaxed), std::memory_order_release);
}

} // namespace dav
