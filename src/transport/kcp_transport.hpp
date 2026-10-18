#pragma once

#include "src/transport/transport.hpp"
#include "src/transport/udp_socket.hpp"
#include "src/core/config.hpp"
#include "third_party/kcp/ikcp.h"
#include <atomic>
#include <thread>
#include <mutex>
#include <vector>

namespace dav {

class KcpTransport : public ITransport {
public:
    explicit KcpTransport(const TransportConfig& config);
    ~KcpTransport() override;

    VoidResult start() override;
    void stop() override;
    [[nodiscard]] bool is_connected() const noexcept override;

    VoidResult send(ConstByteSpan data) override;
    void set_on_data_received(DataReceivedCallback cb) override;
    void update() override;

    [[nodiscard]] TransportStats get_stats() const noexcept override;
    [[nodiscard]] TransportMode get_mode() const noexcept override { return TransportMode::KCP; }

    // Direct access to underlying socket for port querying
    [[nodiscard]] const UdpSocket& get_socket() const noexcept { return socket_; }

private:
    static int kcp_output_callback(const char *buf, int len, ikcpcb *kcp, void *user);
    int handle_kcp_output(const char *buf, int len);
    void poll_udp_socket();
    void process_kcp_recv();

    TransportConfig config_;
    UdpSocket socket_;
    ikcpcb* kcp_{nullptr};
    
    std::mutex kcp_mutex_;
    std::atomic<bool> running_{false};
    std::atomic<bool> connected_{false};
    DataReceivedCallback on_data_received_;

    // Performance Stats
    std::atomic<uint64_t> bytes_sent_{0};
    std::atomic<uint64_t> bytes_received_{0};
    std::atomic<uint64_t> packets_sent_{0};
    std::atomic<uint64_t> packets_received_{0};
    std::atomic<uint64_t> packets_retransmitted_{0};
    
    std::vector<Byte> recv_buffer_;
    std::vector<Byte> udp_raw_buffer_;
};

} // namespace dav
