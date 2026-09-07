#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
#include "protocol.hpp"
#include <atomic>
#include <charconv>
#include <chrono>
#include <iostream>
#include <thread>

namespace {
using namespace fluidgateway;
using Clock = std::chrono::steady_clock;
std::atomic_bool stopping = false;
BOOL WINAPI stop_handler(DWORD event) {
    if (event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT || event == CTRL_CLOSE_EVENT) {
        stopping.store(true); return TRUE;
    }
    return FALSE;
}
struct Socket {
    SOCKET value = INVALID_SOCKET;
    ~Socket() { if (value != INVALID_SOCKET) closesocket(value); }
};
bool ready(SOCKET socket, short events, Clock::time_point deadline) {
    while (!stopping.load()) {
        const auto left = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - Clock::now()).count();
        if (left <= 0) return false;
        WSAPOLLFD poll{socket, events, 0};
        const auto result = WSAPoll(&poll, 1, static_cast<int>(std::min<std::int64_t>(left, 250)));
        if (result == SOCKET_ERROR) return false;
        if (result > 0) return (poll.revents & events) != 0;
    }
    return false;
}
bool receive(SOCKET socket, std::span<std::uint8_t> bytes, Clock::time_point deadline) {
    while (!bytes.empty()) {
        if (!ready(socket, POLLRDNORM, deadline)) return false;
        const auto count = recv(socket, reinterpret_cast<char*>(bytes.data()), static_cast<int>(bytes.size()), 0);
        if (count == SOCKET_ERROR && WSAGetLastError() == WSAEWOULDBLOCK) continue;
        if (count <= 0) return false;
        bytes = bytes.subspan(static_cast<std::size_t>(count));
    }
    return true;
}
bool send_frame(SOCKET socket, std::span<const std::uint8_t> bytes) {
    const auto deadline = Clock::now() + std::chrono::seconds(2);
    while (!bytes.empty()) {
        if (!ready(socket, POLLWRNORM, deadline)) return false;
        const auto count = send(socket, reinterpret_cast<const char*>(bytes.data()), static_cast<int>(bytes.size()), 0);
        if (count == SOCKET_ERROR && WSAGetLastError() == WSAEWOULDBLOCK) continue;
        if (count <= 0) return false;
        bytes = bytes.subspan(static_cast<std::size_t>(count));
    }
    return true;
}
void serve(SOCKET connected) noexcept {
    Socket socket{connected};
    try {
        Identity identity{};
        if (BCryptGenRandom(nullptr, identity.data(), static_cast<ULONG>(identity.size()), BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0)
            return;
        // RFC 4122 byte order, as used by Python uuid4().bytes and FluidLink.
        identity[6] = static_cast<std::uint8_t>((identity[6] & 15) | 64);
        identity[8] = static_cast<std::uint8_t>((identity[8] & 63) | 128);
        ProtocolSession session(identity);
        bool first = true;
        while (!stopping.load() && !session.closed) {
            Bytes wire(header_size);
            const auto prefix_count = first ? 5u : 1u;
            if (!receive(connected, std::span(wire).first(prefix_count),
                Clock::now() + std::chrono::seconds(first ? 1 : 30))) break;
            const auto deadline = Clock::now() + std::chrono::seconds(2);
            if (first && (wire[0] != 'F' || wire[1] != 'L' || wire[2] != 'N' || wire[3] != 'K' || wire[4] != 2)) break;
            first = false;
            if (!receive(connected, std::span(wire).subspan(prefix_count), deadline)) break;
            const auto size = payload_size(wire);
            wire.resize(header_size + size);
            if (!receive(connected, std::span(wire).subspan(header_size), deadline)) break;
            const auto response = session.process(decode_frame(wire));
            if (!send_frame(connected, encode_frame(response))) break;
        }
    } catch (...) {
        // Any malformed frame or allocation failure retires this connection only.
    }
}
struct Worker {
    std::thread thread;
    std::atomic_bool done = true;
    ~Worker() { if (thread.joinable()) thread.join(); }
};
}
int main(int argc, char** argv) {
    if (argc == 2 && std::string_view(argv[1]) == "--version") {
        std::cout << "fluidgateway-native " << fluidgateway::native_version << '\n'; return 0;
    }
    unsigned port = 8765;
    if (argc < 2 || std::string_view(argv[1]) != "serve-events") {
        std::cerr << "Usage: fluidgateway-native serve-events [--host 127.0.0.1] [--port 8765]\n"; return 2;
    }
    for (int i = 2; i < argc; i += 2) {
        if (i + 1 == argc) return 2;
        const std::string_view key(argv[i]), value(argv[i + 1]);
        if (key == "--host") { if (value != "127.0.0.1") return 2; }
        else if (key == "--port") {
            const auto parsed = std::from_chars(value.data(), value.data() + value.size(), port);
            if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || !port || port > 65535) return 2;
        } else return 2;
    }
    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data)) return 1;
    int exit_code = 0;
    try {
        Socket listener{socket(AF_INET, SOCK_STREAM, IPPROTO_TCP)};
        if (listener.value == INVALID_SOCKET) throw std::runtime_error("Cannot create listener.");
        BOOL exclusive = TRUE;
        if (setsockopt(listener.value, SOL_SOCKET, SO_EXCLUSIVEADDRUSE,
            reinterpret_cast<const char*>(&exclusive), sizeof(exclusive))) throw std::runtime_error("Cannot protect listener.");
        sockaddr_in address{}; address.sin_family = AF_INET;
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK); address.sin_port = htons(static_cast<u_short>(port));
        if (bind(listener.value, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) || listen(listener.value, 16))
            throw std::runtime_error("Cannot bind/listen; the port may already be in use.");
        u_long nonblocking = 1;
        if (ioctlsocket(listener.value, FIONBIO, &nonblocking)) throw std::runtime_error("Cannot set nonblocking mode.");
        if (!SetConsoleCtrlHandler(stop_handler, TRUE)) throw std::runtime_error("Cannot register shutdown handler.");
        std::array<Worker, 8> workers;
        std::cout << "FluidGateway native listening on 127.0.0.1:" << port << std::endl;
        while (!stopping.load()) {
            if (!ready(listener.value, POLLRDNORM, Clock::now() + std::chrono::milliseconds(250))) continue;
            const auto connected = accept(listener.value, nullptr, nullptr);
            if (connected == INVALID_SOCKET) continue;
            Worker* available = nullptr;
            for (auto& worker : workers) if (worker.done.load()) { available = &worker; break; }
            if (!available) { closesocket(connected); continue; }
            if (available->thread.joinable()) available->thread.join();
            available->done.store(false);
            try {
                available->thread = std::thread([available, connected] { serve(connected); available->done.store(true); });
            } catch (...) { closesocket(connected); available->done.store(true); stopping.store(true); }
        }
        // Worker destructors join after the stop flag wakes bounded reads/writes.
    } catch (const std::exception& e) { stopping.store(true); std::cerr << e.what() << '\n'; exit_code = 1; }
    WSACleanup(); return exit_code;
}
