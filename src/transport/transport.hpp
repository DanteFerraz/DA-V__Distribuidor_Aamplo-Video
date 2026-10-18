#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include <functional>
#include <string_view>
#include <memory>

namespace dav {

using DataReceivedCallback = std::function<void(ConstByteSpan data)>;

struct TransportStats {
    uint64_t bytes_sent{0};
    uint64_t bytes_received{0};
    uint64_t packets_sent{0};
    uint64_t packets_received{0};
    uint64_t packets_lost{0};
    uint64_t packets_retransmitted{0};
    double rtt_ms{0.0};
    double loss_rate{0.0};
    uint32_t current_bandwidth_kbps{0};
};

class ITransport {
public:
    virtual ~ITransport() = default;

    virtual VoidResult start() = 0;
    virtual void stop() = 0;
    virtual bool is_connected() const noexcept = 0;

    virtual VoidResult send(ConstByteSpan data) = 0;
    virtual void set_on_data_received(DataReceivedCallback cb) = 0;
    virtual void update() = 0;

    [[nodiscard]] virtual TransportStats get_stats() const noexcept = 0;
    [[nodiscard]] virtual TransportMode get_mode() const noexcept = 0;
};

} // namespace dav
