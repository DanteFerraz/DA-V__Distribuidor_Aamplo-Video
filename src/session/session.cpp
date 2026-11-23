// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
// Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
#include "src/session/session.hpp"
#include "src/core/logger.hpp"
#include "src/core/time.hpp"
#include <cstring>

namespace dav {

Session::Session(std::string session_id, std::string peer_id, const AppConfig& config)
    : session_id_(std::move(session_id)),
      peer_id_(std::move(peer_id)),
      config_(config),
      qos_(config.qos, config.capture.target_resolution),
      crypto_(ConstByteSpan(reinterpret_cast<const Byte*>(config.crypto.psk_secret.data()), config.crypto.psk_secret.size())) {
    
    info_.session_id = session_id_;
    info_.peer_id = peer_id_;
    info_.state = SessionState::Disconnected;

    TransportConfig t_cfg = config.transport;
    transport_ = std::make_unique<KcpTransport>(t_cfg);
}

void Session::set_state(SessionState new_state) {
    if (state_ != new_state) {
        log::info("Session [{}] state transition: {} -> {}",
                  session_id_, static_cast<int>(state_), static_cast<int>(new_state));
        state_ = new_state;
        info_.state = new_state;
    }
}

VoidResult Session::connect(std::string_view host, uint16_t port) {
    info_.peer_ip = host;
    info_.peer_port = port;
    set_state(SessionState::Connecting);

    auto start_res = transport_->start();
    if (!start_res.has_value()) {
        set_state(SessionState::Disconnected);
        return start_res;
    }

    transport_->set_on_data_received([this](ConstByteSpan data) {
        if (data.size() < PacketHeader::HeaderSize) return;

        DavPacket packet{};
        if (!PacketHeader::from_wire_bytes(data.data(), data.size(), packet.header)) {
            return;
        }

        size_t payload_len = packet.header.payload_length;
        if (data.size() >= PacketHeader::HeaderSize + payload_len) {
            packet.payload.assign(
                data.data() + PacketHeader::HeaderSize,
                data.data() + PacketHeader::HeaderSize + payload_len
            );
        }

        // Decrypt if encrypted (verify 16B Poly1305 AEAD tag)
        if (packet.header.is_encrypted()) {
            if (data.size() >= PacketHeader::HeaderSize + payload_len + CryptoChannel::TagSize) {
                packet.auth_tag.assign(
                    data.data() + PacketHeader::HeaderSize + payload_len,
                    data.data() + PacketHeader::HeaderSize + payload_len + CryptoChannel::TagSize
                );
            }
            if (!crypto_.decrypt_packet(packet).has_value()) {
                return;
            }
        }

        uint64_t now_us = time::now_microseconds();
        info_.last_activity_us = now_us;
        qos_.on_packet_received(packet, now_us);

        if (on_packet_received_) {
            on_packet_received_(packet);
        }
    });

    set_state(SessionState::Streaming);
    info_.connected_at_us = time::now_microseconds();
    return {};
}

void Session::disconnect() {
    set_state(SessionState::Closed);
    if (transport_) {
        transport_->stop();
    }
}

void Session::update(uint64_t now_us) {
    if (transport_) {
        transport_->update();
    }
    (void)now_us;
}

VoidResult Session::send_frame(const std::vector<DavPacket>& packets) {
    if (state_ != SessionState::Streaming) {
        return make_error(ErrorCode::SessionClosed, "Session is not in streaming state");
    }

    // Process with QoS (add FEC parity)
    uint32_t block_id = packets.empty() ? 0 : packets[0].header.frame_id;
    auto processed_packets = qos_.process_outgoing_packets(packets, block_id);

    // Encrypt & Send
    for (auto& p : processed_packets) {
        if (config_.crypto.enabled) {
            crypto_.encrypt_packet(p);
        }
        auto serialized = p.serialize();
        transport_->send(ConstByteSpan(serialized.data(), serialized.size()));
    }

    return {};
}

void Session::set_on_packet_received(std::function<void(const DavPacket&)> cb) {
    on_packet_received_ = std::move(cb);
}

} // namespace dav
