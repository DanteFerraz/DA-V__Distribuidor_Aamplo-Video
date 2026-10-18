#pragma once

#include "src/session/session.hpp"
#include "src/session/peer_registry.hpp"
#include "src/core/config.hpp"
#include <map>
#include <memory>
#include <mutex>

namespace dav {

class SessionManager {
public:
    explicit SessionManager(const AppConfig& config);
    ~SessionManager() = default;

    Result<std::shared_ptr<Session>> create_session(const std::string& session_id, const std::string& peer_id);
    void close_session(const std::string& session_id);
    std::shared_ptr<Session> get_session(const std::string& session_id);

    void update_all(uint64_t now_us);
    void broadcast_frame(const std::vector<DavPacket>& packets);

    [[nodiscard]] size_t get_active_session_count() const noexcept;
    [[nodiscard]] PeerRegistry& get_peer_registry() noexcept { return peer_registry_; }

private:
    AppConfig config_;
    PeerRegistry peer_registry_;
    std::map<std::string, std::shared_ptr<Session>> sessions_;
    mutable std::mutex mutex_;
};

} // namespace dav
