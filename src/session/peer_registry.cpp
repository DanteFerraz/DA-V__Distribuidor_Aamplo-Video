#include "src/session/peer_registry.hpp"

namespace dav {

void PeerRegistry::register_peer(const DiscoveredPeer& peer) {
    std::lock_guard<std::mutex> lock(mutex_);
    peers_[peer.peer_id] = peer;
}

void PeerRegistry::unregister_peer(const std::string& peer_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    peers_.erase(peer_id);
}

std::vector<DiscoveredPeer> PeerRegistry::get_active_peers(uint64_t now_us, uint64_t max_age_us) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<DiscoveredPeer> active;
    
    auto it = peers_.begin();
    while (it != peers_.end()) {
        if (now_us > it->second.last_seen_us && (now_us - it->second.last_seen_us) > max_age_us) {
            it = peers_.erase(it);
        } else {
            active.push_back(it->second);
            ++it;
        }
    }
    return active;
}

std::optional<DiscoveredPeer> PeerRegistry::find_peer(const std::string& peer_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = peers_.find(peer_id);
    if (it != peers_.end()) {
        return it->second;
    }
    return std::nullopt;
}

void PeerRegistry::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    peers_.clear();
}

} // namespace dav
