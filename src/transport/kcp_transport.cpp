#include "src/transport/kcp_transport.hpp"
#include "src/core/logger.hpp"
#include "src/core/time.hpp"

namespace dav {

int KcpTransport::kcp_output_callback(const char *buf, int len, ikcpcb *kcp, void *user) {
    (void)kcp;
    auto* self = static_cast<KcpTransport*>(user);
    if (!self) return -1;
    return self->handle_kcp_output(buf, len);
}

int KcpTransport::handle_kcp_output(const char *buf, int len) {
    if (len <= 0) return 0;
    auto res = socket_.send(ConstByteSpan(reinterpret_cast<const Byte*>(buf), static_cast<size_t>(len)));
    if (res.has_value() && *res > 0) {
        bytes_sent_ += *res;
        packets_sent_++;
        return 0;
    }
    return -1;
}

KcpTransport::KcpTransport(const TransportConfig& config)
    : config_(config),
      recv_buffer_(65536, 0),
      udp_raw_buffer_(65536, 0) {
}

KcpTransport::~KcpTransport() {
    stop();
}

VoidResult KcpTransport::start() {
    if (running_) return {};

    // 1. Initialize UDP Socket
    auto bind_res = socket_.bind(config_.bind_port);
    if (!bind_res.has_value()) {
        log::error("KCP failed to bind UDP socket on port {}: {}", config_.bind_port, bind_res.error().message);
        return bind_res;
    }

    auto dest_res = socket_.set_destination(config_.remote_host, config_.remote_port);
    if (!dest_res.has_value()) {
        log::error("KCP failed to set destination: {}", dest_res.error().message);
        return dest_res;
    }

    socket_.set_nonblocking(true);
    socket_.set_buffer_sizes(2 * 1024 * 1024, 2 * 1024 * 1024); // 2MB buffers

    // 2. Initialize KCP Control Block
    {
        std::lock_guard<std::mutex> lock(kcp_mutex_);
        kcp_ = ikcp_create(config_.conv_id, this);
        if (!kcp_) {
            return make_error(ErrorCode::OutOfMemory, "Failed to create KCP instance");
        }

        ikcp_setoutput(kcp_, kcp_output_callback);
        ikcp_setmtu(kcp_, static_cast<int>(config_.mtu));
        ikcp_wndsize(kcp_, static_cast<int>(config_.snd_wnd), static_cast<int>(config_.rcv_wnd));
        
        // Fast mode: nodelay=1, interval=10ms, resend=2, nc=1 (disable congestion window)
        ikcp_nodelay(kcp_, config_.kcp_nodelay, config_.kcp_interval, config_.kcp_resend, config_.kcp_nc);
    }

    running_ = true;
    connected_ = true;
    log::info("KCP Transport started on UDP port {} -> {}:{} (Conv: {:#x})",
              config_.bind_port, config_.remote_host, config_.remote_port, config_.conv_id);
    return {};
}

void KcpTransport::stop() {
    if (!running_) return;
    running_ = false;
    connected_ = false;

    {
        std::lock_guard<std::mutex> lock(kcp_mutex_);
        if (kcp_) {
            ikcp_release(kcp_);
            kcp_ = nullptr;
        }
    }

    socket_.close();
    log::info("KCP Transport stopped.");
}

bool KcpTransport::is_connected() const noexcept {
    return connected_ && running_;
}

VoidResult KcpTransport::send(ConstByteSpan data) {
    if (!running_ || !kcp_) {
        return make_error(ErrorCode::SessionClosed, "Transport is not running");
    }

    std::lock_guard<std::mutex> lock(kcp_mutex_);
    int res = ikcp_send(kcp_, reinterpret_cast<const char*>(data.data()), static_cast<int>(data.size()));
    if (res < 0) {
        return make_error(ErrorCode::BufferOverflow, std::format("ikcp_send failed with code {}", res));
    }
    
    ikcp_flush(kcp_);
    return {};
}

void KcpTransport::set_on_data_received(DataReceivedCallback cb) {
    on_data_received_ = std::move(cb);
}

void KcpTransport::poll_udp_socket() {
    while (running_) {
        auto recv_res = socket_.receive(MutableByteSpan(udp_raw_buffer_));
        if (!recv_res.has_value() || *recv_res == 0) {
            break; // No more data available right now
        }

        bytes_received_ += *recv_res;
        packets_received_++;

        std::lock_guard<std::mutex> lock(kcp_mutex_);
        if (kcp_) {
            ikcp_input(kcp_, reinterpret_cast<const char*>(udp_raw_buffer_.data()), static_cast<long>(*recv_res));
        }
    }
}

void KcpTransport::process_kcp_recv() {
    std::lock_guard<std::mutex> lock(kcp_mutex_);
    if (!kcp_ || !on_data_received_) return;

    while (true) {
        int peek_size = ikcp_peeksize(kcp_);
        if (peek_size <= 0) break;

        if (static_cast<size_t>(peek_size) > recv_buffer_.size()) {
            recv_buffer_.resize(static_cast<size_t>(peek_size) * 2);
        }

        int bytes_read = ikcp_recv(kcp_, reinterpret_cast<char*>(recv_buffer_.data()), static_cast<int>(recv_buffer_.size()));
        if (bytes_read > 0) {
            on_data_received_(ConstByteSpan(recv_buffer_.data(), static_cast<size_t>(bytes_read)));
        } else {
            break;
        }
    }
}

void KcpTransport::update() {
    if (!running_) return;

    // 1. Read all incoming UDP packets
    poll_udp_socket();

    // 2. Update KCP state machine & flush outgoing
    uint32_t current_ms = time::now_milliseconds();
    {
        std::lock_guard<std::mutex> lock(kcp_mutex_);
        if (kcp_) {
            ikcp_update(kcp_, current_ms);
        }
    }

    // 3. Process completed frames/messages
    process_kcp_recv();
}

TransportStats KcpTransport::get_stats() const noexcept {
    TransportStats stats{};
    stats.bytes_sent = bytes_sent_.load();
    stats.bytes_received = bytes_received_.load();
    stats.packets_sent = packets_sent_.load();
    stats.packets_received = packets_received_.load();
    stats.packets_retransmitted = packets_retransmitted_.load();
    
    if (kcp_) {
        stats.rtt_ms = static_cast<double>(kcp_->rx_srtt);
    }
    return stats;
}

} // namespace dav
