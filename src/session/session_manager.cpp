#include "src/session/session_manager.hpp"
#include "src/core/logger.hpp"

namespace dav {

SessionManager::SessionManager(const AppConfig& config)
    : config_(config) {
}

Result<std::shared_ptr<Session>> SessionManager::create_session(const std::string& session_id, const std::string& peer_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    if (sessions_.find(session_id) != sessions_.end()) {
        return make_error(ErrorCode::AlreadyExists, std::format("Session {} already exists", session_id));
    }

    auto session = std::make_shared<Session>(session_id, peer_id, config_);
    sessions_[session_id] = session;
    log::info("SessionManager created session: {} for peer: {}", session_id, peer_id);
    return session;
}

void SessionManager::close_session(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = sessions_.find(session_id);
    if (it != sessions_.end()) {
        it->second->disconnect();
        sessions_.erase(it);
        log::info("SessionManager closed session: {}", session_id);
    }
}

std::shared_ptr<Session> SessionManager::get_session(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = sessions_.find(session_id);
    if (it != sessions_.end()) {
        return it->second;
    }
    return nullptr;
}

void SessionManager::update_all(uint64_t now_us) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& [id, sess] : sessions_) {
        sess->update(now_us);
    }
}

void SessionManager::broadcast_frame(const std::vector<DavPacket>& packets) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& [id, sess] : sessions_) {
        sess->send_frame(packets);
    }
}

size_t SessionManager::get_active_session_count() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return sessions_.size();
}

} // namespace dav
