#include "src/metrics/metrics_registry.hpp"
#include <iomanip>

namespace dav {

MetricsRegistry& MetricsRegistry::instance() {
    static MetricsRegistry reg;
    return reg;
}

void MetricsRegistry::set_capture_fps(double fps) noexcept { capture_fps_.store(fps); }
void MetricsRegistry::set_encode_fps(double fps) noexcept { encode_fps_.store(fps); }
void MetricsRegistry::set_encode_bitrate_bps(uint64_t bps) noexcept { encode_bitrate_bps_.store(bps); }
void MetricsRegistry::set_transport_rtt_ms(double rtt_ms) noexcept { rtt_ms_.store(rtt_ms); }
void MetricsRegistry::set_transport_loss_rate(double loss) noexcept { loss_rate_.store(loss); }
void MetricsRegistry::set_jitter_ms(double jitter_ms) noexcept { jitter_ms_.store(jitter_ms); }
void MetricsRegistry::set_fec_overhead_pct(double pct) noexcept { fec_overhead_pct_.store(pct); }
void MetricsRegistry::set_active_sessions(uint32_t count) noexcept { active_sessions_.store(count); }

void MetricsRegistry::increment_frames_captured(uint64_t count) noexcept { frames_captured_total_ += count; }
void MetricsRegistry::increment_frames_encoded(uint64_t count) noexcept { frames_encoded_total_ += count; }
void MetricsRegistry::increment_packets_sent(uint64_t count) noexcept { packets_sent_total_ += count; }
void MetricsRegistry::increment_packets_received(uint64_t count) noexcept { packets_received_total_ += count; }
void MetricsRegistry::increment_nacks_sent(uint64_t count) noexcept { nacks_sent_total_ += count; }
void MetricsRegistry::increment_frames_dropped(uint64_t count) noexcept { frames_dropped_total_ += count; }

std::string MetricsRegistry::export_prometheus_text() const {
    std::ostringstream ss;
    
    // Help and Type headers
    ss << "# HELP dav_capture_fps Current desktop screen capture framerate\n";
    ss << "# TYPE dav_capture_fps gauge\n";
    ss << "dav_capture_fps " << std::fixed << std::setprecision(2) << capture_fps_.load() << "\n\n";

    ss << "# HELP dav_encode_fps Current video encoding framerate\n";
    ss << "# TYPE dav_encode_fps gauge\n";
    ss << "dav_encode_fps " << std::fixed << std::setprecision(2) << encode_fps_.load() << "\n\n";

    ss << "# HELP dav_encode_bitrate_bps Video bitstream output rate in bits per second\n";
    ss << "# TYPE dav_encode_bitrate_bps gauge\n";
    ss << "dav_encode_bitrate_bps " << encode_bitrate_bps_.load() << "\n\n";

    ss << "# HELP dav_transport_rtt_ms Round trip time in milliseconds\n";
    ss << "# TYPE dav_transport_rtt_ms gauge\n";
    ss << "dav_transport_rtt_ms " << std::fixed << std::setprecision(2) << rtt_ms_.load() << "\n\n";

    ss << "# HELP dav_transport_loss_rate Packet loss ratio (0.0 to 1.0)\n";
    ss << "# TYPE dav_transport_loss_rate gauge\n";
    ss << "dav_transport_loss_rate " << std::fixed << std::setprecision(4) << loss_rate_.load() << "\n\n";

    ss << "# HELP dav_jitter_ms Inter-arrival jitter in milliseconds\n";
    ss << "# TYPE dav_jitter_ms gauge\n";
    ss << "dav_jitter_ms " << std::fixed << std::setprecision(2) << jitter_ms_.load() << "\n\n";

    ss << "# HELP dav_fec_overhead_pct Forward error correction parity overhead percentage\n";
    ss << "# TYPE dav_fec_overhead_pct gauge\n";
    ss << "dav_fec_overhead_pct " << std::fixed << std::setprecision(1) << fec_overhead_pct_.load() << "\n\n";

    ss << "# HELP dav_active_sessions Number of active streaming sessions\n";
    ss << "# TYPE dav_active_sessions gauge\n";
    ss << "dav_active_sessions " << active_sessions_.load() << "\n\n";

    ss << "# HELP dav_frames_captured_total Cumulative number of captured frames\n";
    ss << "# TYPE dav_frames_captured_total counter\n";
    ss << "dav_frames_captured_total " << frames_captured_total_.load() << "\n\n";

    ss << "# HELP dav_frames_encoded_total Cumulative number of encoded frames\n";
    ss << "# TYPE dav_frames_encoded_total counter\n";
    ss << "dav_frames_encoded_total " << frames_encoded_total_.load() << "\n\n";

    ss << "# HELP dav_packets_sent_total Cumulative number of network packets transmitted\n";
    ss << "# TYPE dav_packets_sent_total counter\n";
    ss << "dav_packets_sent_total " << packets_sent_total_.load() << "\n\n";

    ss << "# HELP dav_packets_received_total Cumulative number of network packets received\n";
    ss << "# TYPE dav_packets_received_total counter\n";
    ss << "dav_packets_received_total " << packets_received_total_.load() << "\n\n";

    return ss.str();
}

} // namespace dav
