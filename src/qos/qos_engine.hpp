#pragma once

#include "src/core/config.hpp"
#include "src/qos/fec.hpp"
#include "src/qos/adaptive_bitrate.hpp"
#include "src/qos/jitter_buffer.hpp"
#include "src/qos/nack_handler.hpp"
#include "src/transport/bandwidth_estimator.hpp"
#include <memory>

namespace dav {

struct QosMetricsSnapshot {
    uint32_t current_bitrate_kbps{8000};
    uint32_t target_fps{60};
    double rtt_ms{0.0};
    double jitter_ms{0.0};
    double loss_rate{0.0};
    double fec_overhead_pct{20.0};
    uint64_t nacks_sent{0};
    uint32_t jitter_buffer_delay_ms{10};
};

class QosEngine {
public:
    explicit QosEngine(const QosConfig& config, const Resolution& base_res = {1920, 1080});
    ~QosEngine() = default;

    // Sender pipeline hooks
    std::vector<DavPacket> process_outgoing_packets(std::vector<DavPacket> packets, uint32_t block_id);
    AbrDecision evaluate_network_conditions(uint32_t outgoing_queue_size);

    // Receiver pipeline hooks
    void on_packet_received(const DavPacket& packet, uint64_t arrival_time_us);
    std::optional<DavPacket> fetch_playable_packet(uint64_t current_time_us);
    std::vector<uint32_t> poll_nacks(uint64_t now_us);
    void on_rtt_feedback(double rtt_ms, double loss_rate);

    [[nodiscard]] QosMetricsSnapshot get_snapshot() const noexcept;
    void reset();

private:
    QosConfig config_;
    FecHandler fec_;
    AdaptiveBitrateController abr_;
    JitterBuffer jitter_buffer_;
    NackHandler nack_handler_;
    BandwidthEstimator bw_estimator_;
};

} // namespace dav
