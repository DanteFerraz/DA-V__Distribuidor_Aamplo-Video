// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
// Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
#pragma once

#include "src/core/types.hpp"
#include "src/core/result.hpp"
#include <atomic>
#include <thread>
#include <string>

namespace dav {

class HttpMetricsExporter {
public:
    explicit HttpMetricsExporter(uint16_t port = 9200);
    ~HttpMetricsExporter();

    VoidResult start();
    void stop();
    [[nodiscard]] bool is_running() const noexcept { return running_; }

private:
    void server_loop();

    uint16_t port_;
    std::atomic<bool> running_{false};
    std::thread server_thread_;
};

} // namespace dav
