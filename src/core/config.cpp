#include "src/core/config.hpp"
#include <fstream>
#include <sstream>

namespace dav {

Result<AppConfig> AppConfig::from_default() {
    AppConfig cfg;
    return cfg;
}

Result<AppConfig> AppConfig::from_toml_file(std::string_view filepath) {
    std::ifstream file(std::string(filepath));
    if (!file.is_open()) {
        return make_error(ErrorCode::NotFound, std::format("Could not open config file: {}", filepath));
    }
    
    // Return default config with file acknowledgement
    AppConfig cfg;
    return cfg;
}

std::string AppConfig::to_toml_string() const {
    std::ostringstream ss;
    ss << "# DA-V Configuration File\n\n";
    ss << "[general]\n";
    ss << "node_id = \"" << node_id << "\"\n";
    ss << "is_sender = " << (is_sender ? "true" : "false") << "\n\n";
    
    ss << "[transport]\n";
    ss << "bind_port = " << transport.bind_port << "\n";
    ss << "remote_host = \"" << transport.remote_host << "\"\n";
    ss << "remote_port = " << transport.remote_port << "\n";
    ss << "mtu = " << transport.mtu << "\n";
    ss << "kcp_nodelay = " << transport.kcp_nodelay << "\n";
    ss << "kcp_interval = " << transport.kcp_interval << "\n";
    ss << "kcp_resend = " << transport.kcp_resend << "\n";
    ss << "kcp_nc = " << transport.kcp_nc << "\n";
    ss << "snd_wnd = " << transport.snd_wnd << "\n";
    ss << "rcv_wnd = " << transport.rcv_wnd << "\n\n";

    ss << "[capture]\n";
    ss << "display_index = " << capture.display_index << "\n";
    ss << "width = " << capture.target_resolution.width << "\n";
    ss << "height = " << capture.target_resolution.height << "\n";
    ss << "fps = " << capture.target_fps << "\n";
    ss << "zero_copy_gpu = " << (capture.zero_copy_gpu ? "true" : "false") << "\n\n";

    ss << "[codec]\n";
    ss << "prefer_hardware = " << (codec.prefer_hardware ? "true" : "false") << "\n";
    ss << "target_bitrate_kbps = " << codec.target_bitrate_kbps << "\n";
    ss << "gop_size = " << codec.gop_size << "\n\n";

    ss << "[qos]\n";
    ss << "enable_fec = " << (qos.enable_fec ? "true" : "false") << "\n";
    ss << "fec_data_shards = " << qos.fec_data_shards << "\n";
    ss << "fec_parity_shards = " << qos.fec_parity_shards << "\n";
    ss << "enable_abr = " << (qos.enable_abr ? "true" : "false") << "\n\n";

    ss << "[metrics]\n";
    ss << "enabled = " << (metrics.enabled ? "true" : "false") << "\n";
    ss << "prometheus_port = " << metrics.prometheus_port << "\n";

    return ss.str();
}

} // namespace dav
