#include "src/qos/qos_engine.hpp"

namespace dav {

QosEngine::QosEngine(const QosConfig& config, const Resolution& base_res)
    : config_(config),
      fec_(static_cast<uint8_t>(config.fec_data_shards), static_cast<uint8_t>(config.fec_parity_shards)),
      abr_(1000, 25000, base_res),
      jitter_buffer_(config.jitter_buffer_min_ms, config.jitter_buffer_max_ms),
      nack_handler_(15.0, 3),
      bw_estimator_(1000000, 30000000) {
}

void QosEngine::reset() {
    abr_.reset();
    jitter_buffer_.reset();
    nack_handler_.reset();
    bw_estimator_.reset();
}

std::vector<DavPacket> QosEngine::process_outgoing_packets(std::vector<DavPacket> packets, uint32_t block_id) {
    if (!config_.enable_fec || packets.empty()) return packets;

    auto parity = fec_.generate_parity(packets, block_id);
    packets.insert(packets.end(), std::make_move_iterator(parity.begin()), std::make_move_iterator(parity.end()));
    return packets;
}

AbrDecision QosEngine::evaluate_network_conditions(uint32_t outgoing_queue_size) {
    auto bw_est = bw_estimator_.get_estimate();
    auto decision = abr_.evaluate(bw_est, outgoing_queue_size);
    
    // Dynamically adjust FEC ratio based on ABR recommendation
    uint8_t data_shards = 10;
    uint8_t parity_shards = static_cast<uint8_t>(10 * decision.recommended_fec_ratio);
    fec_.set_overhead_ratio(data_shards, std::max((uint8_t)1, parity_shards));

    return decision;
}

void QosEngine::on_packet_received(const DavPacket& packet, uint64_t arrival_time_us) {
    bw_estimator_.on_packet_received(packet.payload.size(), arrival_time_us, packet.header.timestamp_us);
    nack_handler_.on_packet_received(packet.header.sequence_number, arrival_time_us);
    jitter_buffer_.push_packet(packet, arrival_time_us);
}

std::optional<DavPacket> QosEngine::fetch_playable_packet(uint64_t current_time_us) {
    return jitter_buffer_.pop_packet(current_time_us);
}

std::vector<uint32_t> QosEngine::poll_nacks(uint64_t now_us) {
    if (!config_.enable_nack) return {};
    return nack_handler_.get_pending_nacks(now_us);
}

void QosEngine::on_rtt_feedback(double rtt_ms, double loss_rate) {
    bw_estimator_.on_feedback(rtt_ms, loss_rate);
    nack_handler_.update_rtt(rtt_ms);
}

QosMetricsSnapshot QosEngine::get_snapshot() const noexcept {
    auto bw_est = bw_estimator_.get_estimate();
    return QosMetricsSnapshot{
        .current_bitrate_kbps = abr_.get_current_bitrate_kbps(),
        .target_fps = abr_.get_current_fps(),
        .rtt_ms = bw_est.rtt_ms,
        .jitter_ms = jitter_buffer_.get_current_jitter_ms(),
        .loss_rate = bw_est.packet_loss_rate,
        .fec_overhead_pct = fec_.get_overhead_percentage(),
        .nacks_sent = nack_handler_.get_total_nacks_sent(),
        .jitter_buffer_delay_ms = jitter_buffer_.get_target_delay_ms()
    };
}

} // namespace dav
