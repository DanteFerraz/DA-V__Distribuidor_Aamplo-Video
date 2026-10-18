#pragma once

#include <string_view>
#include <format>
#include <iostream>
#include <mutex>
#include <chrono>
#include <source_location>

namespace dav::log {

enum class Level {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
    Critical
};

class Logger {
public:
    static Logger& instance();

    void set_level(Level lvl) noexcept;
    [[nodiscard]] Level get_level() const noexcept;

    template <typename... Args>
    void log(Level lvl, std::format_string<Args...> fmt, Args&&... args) {
        if (lvl < current_level_) return;
        std::string msg = std::format(fmt, std::forward<Args>(args)...);
        write_log(lvl, msg);
    }

private:
    Logger() = default;
    void write_log(Level lvl, std::string_view msg);

    Level current_level_{Level::Info};
    std::mutex mutex_;
};

template <typename... Args>
inline void trace(std::format_string<Args...> fmt, Args&&... args) {
    Logger::instance().log(Level::Trace, fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void debug(std::format_string<Args...> fmt, Args&&... args) {
    Logger::instance().log(Level::Debug, fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void info(std::format_string<Args...> fmt, Args&&... args) {
    Logger::instance().log(Level::Info, fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void warn(std::format_string<Args...> fmt, Args&&... args) {
    Logger::instance().log(Level::Warn, fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void error(std::format_string<Args...> fmt, Args&&... args) {
    Logger::instance().log(Level::Error, fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void critical(std::format_string<Args...> fmt, Args&&... args) {
    Logger::instance().log(Level::Critical, fmt, std::forward<Args>(args)...);
}

} // namespace dav::log
