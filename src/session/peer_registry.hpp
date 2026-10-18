#pragma once

#include "src/core/types.hpp"
#include <string>
#include <vector>
#include <map>
#include <mutex>

namespace dav {

struct DiscoveredPeer {
    std::string peer_id;
    std::string hostname;
    std::string ip_address;
    uint16_t port{9000};
    uint64_t last_seen_us{0};
    bool is_lan{true};
};

class PeerRegistry {
public:
    PeerRegistry() = default;
    ~PeerRegistry() = default;

    void register_peer(const DiscoveredPeer& peer);
    void unregister_peer(const std::string& peer_id);
    
    std::vector<DiscoveredPeer> get_active_peers(uint64_t now_us, uint64_t max_age_us = 30000000);
    std::optional<DiscoveredPeer> find_peer(const std::string& peer_id);

    void clear();

private:
    std::map<std::string, DiscoveredPeer> peers_;
    std::mutex mutex_;
};

} // namespace dav
