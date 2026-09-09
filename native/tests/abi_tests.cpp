#include "fluidgateway_native.h"
#include "protocol.hpp"
#include <atomic>
#include <iostream>
#include <thread>

namespace {
using namespace fluidgateway;
void check(bool value, const char* message) {
    if (!value)
        throw std::runtime_error(message);
}
struct OwnedSession {
    fgn_session_handle handle = 0;
    OwnedSession() {
        check(fgn_session_create(FGN_ABI_VERSION, &handle) == FGN_OK, "create");
    }
    ~OwnedSession() {
        fgn_session_destroy(handle);
    }
    OwnedSession(const OwnedSession&) = delete;
    OwnedSession& operator=(const OwnedSession&) = delete;
};
Frame hello() {
    Frame frame;
    frame.opcode = 1;
    frame.message[0] = 1;
    frame.payload = unhex(base_hash);
    for (const auto value : {std::uint64_t{127}, std::uint64_t{27}})
        for (unsigned i = 0; i < 8; ++i)
            frame.payload.push_back(static_cast<std::uint8_t>(value >> (8 * i)));
    frame.payload.insert(frame.payload.end(), {1, 'c', 1, '1'});
    return frame;
}
Frame exchange(fgn_session_handle handle, const Frame& request) {
    const auto wire = encode_frame(request);
    Bytes output(FGN_MAX_FRAME_BYTES);
    uint32_t size = 0;
    check(fgn_session_exchange(handle,
                               wire.data(),
                               static_cast<uint32_t>(wire.size()),
                               output.data(),
                               static_cast<uint32_t>(output.size()),
                               &size) == FGN_OK,
          "exchange");
    return decode_frame(std::span(output).first(size));
}
void lifetime_and_bounds() {
    fgn_session_handle handle = 99;
    check(fgn_session_create(FGN_ABI_VERSION + 1, &handle) == FGN_ABI_MISMATCH && !handle,
          "version mismatch");
    check(fgn_session_create(FGN_ABI_VERSION, nullptr) == FGN_INVALID_ARGUMENT, "null handle");
    fgn_abi_info info{};
    check(fgn_get_abi_info(FGN_ABI_VERSION, &info, sizeof(info) - 1) == FGN_INVALID_ARGUMENT,
          "short info");
    {
        std::array<OwnedSession, FGN_MAX_SESSIONS> sessions;
        check(fgn_session_create(FGN_ABI_VERSION, &handle) == FGN_LIMIT_REACHED && !handle,
              "session bound");
        const auto stale = sessions[0].handle;
        check(fgn_session_destroy(stale) == FGN_OK, "release slot");
        OwnedSession replacement;
        check(replacement.handle != stale, "handle ABA");
        check(fgn_session_destroy(stale) == FGN_INVALID_HANDLE, "stale destroy");
    }
    State empty_state;
    for (unsigned i = 0; i < 2000; ++i) {
        OwnedSession session;
        fgn_session_metrics metrics{};
        check(fgn_session_get_metrics(session.handle, &metrics, sizeof(metrics)) == FGN_OK &&
                  !metrics.tracked_operations && !metrics.active_resources &&
                  metrics.state_bytes == empty_state.budget.used && !metrics.exchanges,
              "renewal must not retain state");
    }
}
void caller_buffers_and_retirement() {
    OwnedSession session;
    const auto request = encode_frame(hello());
    Bytes output(FGN_MAX_FRAME_BYTES + 8, 0xa5);
    uint32_t size = 0;
    check(fgn_session_exchange(session.handle,
                               request.data(),
                               static_cast<uint32_t>(request.size()),
                               output.data(),
                               1,
                               &size) == FGN_BUFFER_TOO_SMALL &&
              size == FGN_MAX_FRAME_BYTES && output.front() == 0xa5,
          "capacity query must not consume a sequence or write a partial response");
    const auto welcome = exchange(session.handle, hello());
    ProtocolSession reference(welcome.session);
    check(encode_frame(reference.process(hello())) == encode_frame(welcome), "same core welcome");
    Frame ping;
    ping.opcode = 20;
    ping.message[0] = 9;
    ping.sequence = 2;
    ping.flags = 2;
    ping.session = welcome.session;
    ping.payload = {1, 'x'};
    const auto input = encode_frame(ping);
    check(fgn_session_exchange(session.handle,
                               input.data(),
                               static_cast<uint32_t>(input.size()),
                               output.data(),
                               FGN_MAX_FRAME_BYTES,
                               &size) == FGN_OK,
          "caller output");
    check(Bytes(output.begin(), output.begin() + size) == encode_frame(reference.process(ping)),
          "shared encoder parity");
    check(output[FGN_MAX_FRAME_BYTES] == 0xa5 && output[size] == 0xa5, "output canary");
    check(fgn_session_exchange(
              session.handle, output.data(), size, output.data(), FGN_MAX_FRAME_BYTES, &size) ==
              FGN_INVALID_ARGUMENT,
          "overlap");
    size = 99;
    check(fgn_session_exchange(
              session.handle, input.data(), 8, output.data(), FGN_MAX_FRAME_BYTES, &size) ==
                  FGN_INVALID_FRAME &&
              !size,
          "truncation retires");
    check(fgn_session_exchange(session.handle,
                               input.data(),
                               static_cast<uint32_t>(input.size()),
                               output.data(),
                               FGN_MAX_FRAME_BYTES,
                               &size) == FGN_SESSION_CLOSED &&
              !size,
          "retired session");
    fgn_session_metrics metrics{};
    check(fgn_session_get_metrics(session.handle, &metrics, sizeof(metrics)) == FGN_OK &&
              metrics.closed && metrics.exchanges == 2 && metrics.wire_payload_copy_count == 4,
          "closed metrics");
}
void concurrent_sessions_and_destroy() {
    std::atomic_bool passed = true;
    {
        std::array<OwnedSession, 8> sessions;
        std::array<std::thread, 8> threads;
        for (std::size_t i = 0; i < threads.size(); ++i)
            threads[i] = std::thread([&, i] {
                try {
                    const auto welcome = exchange(sessions[i].handle, hello());
                    Frame ping;
                    ping.opcode = 20;
                    ping.flags = 2;
                    ping.session = welcome.session;
                    ping.message[0] = 1;
                    ping.payload = {1, 'x'};
                    for (ping.sequence = 2; ping.sequence < 102; ++ping.sequence)
                        check(exchange(sessions[i].handle, ping).opcode == 21, "parallel ping");
                } catch (...) {
                    passed = false;
                }
            });
        for (auto& thread : threads)
            thread.join();
    }
    check(passed, "independent sessions");
    for (unsigned i = 0; i < 100; ++i) {
        OwnedSession session;
        const auto request = encode_frame(hello());
        std::thread caller([&] {
            Bytes output(FGN_MAX_FRAME_BYTES);
            uint32_t size = 0;
            const auto status = fgn_session_exchange(session.handle,
                                                     request.data(),
                                                     static_cast<uint32_t>(request.size()),
                                                     output.data(),
                                                     FGN_MAX_FRAME_BYTES,
                                                     &size);
            if (status != FGN_OK && status != FGN_INVALID_HANDLE && status != FGN_BUSY)
                passed = false;
        });
        check(fgn_session_destroy(session.handle) == FGN_OK, "concurrent destroy");
        caller.join();
    }
    check(passed, "destroy versus exchange");
}

void renewal_does_not_lock_other_sessions() {
    std::atomic_bool passed = true;
    std::array<std::thread, 8> workers;
    for (auto& worker : workers)
        worker = std::thread([&] {
            try {
                for (unsigned i = 0; i < 1000; ++i) {
                    OwnedSession session;
                    const auto welcome = exchange(session.handle, hello());
                    Frame ping;
                    ping.opcode = 20;
                    ping.flags = 2;
                    ping.session = welcome.session;
                    ping.message[0] = 1;
                    ping.sequence = 2;
                    ping.payload = {1, 'x'};
                    check(exchange(session.handle, ping).opcode == 21, "renewal ping");
                }
            } catch (...) {
                passed = false;
            }
        });
    for (auto& worker : workers)
        worker.join();
    check(passed, "session allocation must not cause BUSY in an unrelated session");
}
} // namespace

int main() {
    try {
        lifetime_and_bounds();
        caller_buffers_and_retirement();
        concurrent_sessions_and_destroy();
        renewal_does_not_lock_other_sessions();
        std::cout << "C ABI lifetime, buffers, parity and concurrency passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
