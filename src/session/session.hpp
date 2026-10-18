#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include "src/core/config.hpp"
#include "src/transport/kcp_transport.hpp"
#include "src/qos/qos_engine.hpp"
#include "src/crypto/crypto_channel.hpp"
#include <string>
#include <memory>
#include <chrono>

namespace dav {

struct SessionInfo {
    std::string session_id;
    std::string peer_id;
    std::string peer_ip;
    uint16_t peer_port{0};
    SessionState state{SessionState::Disconnected};
    uint64_t connected_at_us{0};
    uint64_t last_activity_us{0};
    bool is_initiator{false};
};

class Session {
public:
    Session(std::string session_id, std::string peer_id, const AppConfig& config);
    ~Session() = default;

    VoidResult connect(std::string_view host, uint16_t port);
    void disconnect();
    void update(uint64_t now_us);

    [[nodiscard]] SessionState get_state() const noexcept { return state_; }
    [[nodiscard]] const SessionInfo& get_info() const noexcept { return info_; }
    [[nodiscard]] QosEngine& get_qos() noexcept { return qos_; }
    [[nodiscard]] CryptoChannel& get_crypto() noexcept { return crypto_; }

    VoidResult send_frame(const std::vector<DavPacket>& packets);
    void set_on_packet_received(std::function<void(const DavPacket&)> cb);

private:
    void set_state(SessionState new_state);

    std::string session_id_;
    std::string peer_id_;
    AppConfig config_;
    SessionState state_{SessionState::Disconnected};
    SessionInfo info_;

    std::unique_ptr<KcpTransport> transport_;
    QosEngine qos_;
    CryptoChannel crypto_;
    std::function<void(const DavPacket&)> on_packet_received_;
};

} // namespace dav
