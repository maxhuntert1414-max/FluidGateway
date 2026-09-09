#include "fluidgateway_native.h"
#include "protocol.hpp"
#include <windows.h>
#include <bcrypt.h>
#include <array>
#include <atomic>
#include <limits>
#include <memory>
#include <mutex>

namespace {
using namespace fluidgateway;

static_assert(sizeof(fgn_abi_info) == 40);
static_assert(sizeof(fgn_session_metrics) == 96);
static_assert(FGN_MAX_FRAME_BYTES == header_size + max_payload);

struct Session {
    explicit Session(Identity identity) : protocol(identity) {}
    ProtocolSession protocol;
    fgn_session_metrics metrics{};
};
struct Slot {
    std::mutex mutex;
    std::atomic_bool reserved = false;
    std::uint64_t generation = 0;
    fgn_session_handle handle = 0;
    std::unique_ptr<Session> session;
};
std::array<Slot, FGN_MAX_SESSIONS> slots;

struct Reservation {
    Slot& slot;
    bool committed = false;
    ~Reservation() {
        if (!committed)
            slot.reserved.store(false);
    }
};

Slot* find_slot(fgn_session_handle handle) noexcept {
    const auto index = handle & 255;
    if (!handle || !index || index > slots.size())
        return nullptr;
    return &slots[static_cast<std::size_t>(index - 1)];
}
bool overlaps(const void* first,
              std::size_t first_size,
              const void* second,
              std::size_t second_size) noexcept {
    const auto a = reinterpret_cast<std::uintptr_t>(first);
    const auto b = reinterpret_cast<std::uintptr_t>(second);
    if (first_size > UINTPTR_MAX - a || second_size > UINTPTR_MAX - b)
        return true;
    return a < b + second_size && b < a + first_size;
}
void add(std::uint64_t& counter, std::uint64_t value) {
    if (value > UINT64_MAX - counter)
        throw Error(11, "Metric capacity exhausted.", true);
    counter += value;
}
} // namespace

fgn_status FGN_CALL fgn_get_abi_info(uint32_t requested_version,
                                     fgn_abi_info* info,
                                     uint32_t info_size) noexcept {
    if (!info || info_size < sizeof(fgn_abi_info))
        return FGN_INVALID_ARGUMENT;
    *info = {};
    if (requested_version != FGN_ABI_VERSION)
        return FGN_ABI_MISMATCH;
    *info = {FGN_ABI_VERSION,
             sizeof(fgn_abi_info),
             FGN_MAX_FRAME_BYTES,
             FGN_MAX_SESSIONS,
             static_cast<uint32_t>(resource_limit),
             static_cast<uint32_t>(operation_limit),
             state_limit,
             FGN_FEATURE_FLUIDLINK_V2 | FGN_FEATURE_OPERATION_BATCH};
    return FGN_OK;
}

fgn_status FGN_CALL fgn_session_create(uint32_t requested_version,
                                       fgn_session_handle* handle) noexcept {
    if (!handle)
        return FGN_INVALID_ARGUMENT;
    *handle = 0;
    if (requested_version != FGN_ABI_VERSION)
        return FGN_ABI_MISMATCH;
    try {
        for (std::size_t i = 0; i < slots.size(); ++i) {
            auto& slot = slots[i];
            bool available = false;
            if (!slot.reserved.compare_exchange_strong(available, true))
                continue;
            Reservation reservation{slot};
            // Reserving a free slot never touches an active session's exchange lock.
            std::lock_guard lock(slot.mutex);
            if (slot.generation == (UINT64_MAX >> 8)) {
                reservation.committed = true;
                continue;
            }
            Identity identity{};
            if (BCryptGenRandom(nullptr,
                                identity.data(),
                                static_cast<ULONG>(identity.size()),
                                BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0)
                return FGN_INTERNAL_ERROR;
            identity[6] = static_cast<uint8_t>((identity[6] & 15) | 64);
            identity[8] = static_cast<uint8_t>((identity[8] & 63) | 128);
            slot.session = std::make_unique<Session>(identity);
            slot.handle = (++slot.generation << 8) | (i + 1);
            *handle = slot.handle;
            reservation.committed = true;
            return FGN_OK;
        }
        return FGN_LIMIT_REACHED;
    } catch (const std::bad_alloc&) {
        return FGN_OUT_OF_MEMORY;
    } catch (...) {
        return FGN_INTERNAL_ERROR;
    }
}

fgn_status FGN_CALL fgn_session_exchange(fgn_session_handle handle,
                                         const uint8_t* request,
                                         uint32_t request_size,
                                         uint8_t* output,
                                         uint32_t output_capacity,
                                         uint32_t* output_size) noexcept {
    if (!output_size || overlaps(request, request_size, output_size, sizeof(*output_size)) ||
        overlaps(output, output_capacity, output_size, sizeof(*output_size)))
        return FGN_INVALID_ARGUMENT;
    *output_size = 0;
    if (!request || !request_size || overlaps(request, request_size, output, output_capacity))
        return FGN_INVALID_ARGUMENT;
    if (output_capacity < FGN_MAX_FRAME_BYTES) {
        *output_size = FGN_MAX_FRAME_BYTES;
        return FGN_BUFFER_TOO_SMALL;
    }
    if (!output)
        return FGN_INVALID_ARGUMENT;
    auto* slot = find_slot(handle);
    if (!slot)
        return FGN_INVALID_HANDLE;
    try {
        std::unique_lock lock(slot->mutex, std::try_to_lock);
        if (!lock)
            return FGN_BUSY;
        if (slot->handle != handle || !slot->session)
            return FGN_INVALID_HANDLE;
        auto& session = *slot->session;
        if (session.protocol.closed)
            return FGN_SESSION_CLOSED;
        try {
            const auto frame = decode_frame({request, request_size});
            const auto response = session.protocol.process(frame);
            auto& metrics = session.metrics;
            add(metrics.exchanges, 1);
            add(metrics.request_bytes, request_size);
            add(metrics.response_bytes, header_size + response.payload.size());
            add(metrics.wire_payload_copy_bytes, frame.payload.size() + response.payload.size());
            add(metrics.wire_payload_copy_count,
                static_cast<uint64_t>(!frame.payload.empty()) + !response.payload.empty());
            *output_size =
                static_cast<uint32_t>(encode_frame_into(response, {output, output_capacity}));
            return FGN_OK;
        } catch (const Error&) {
            session.protocol.closed = true;
            return FGN_INVALID_FRAME;
        } catch (const std::bad_alloc&) {
            session.protocol.closed = true;
            return FGN_OUT_OF_MEMORY;
        } catch (...) {
            session.protocol.closed = true;
            return FGN_INTERNAL_ERROR;
        }
    } catch (...) {
        return FGN_INTERNAL_ERROR;
    }
}

fgn_status FGN_CALL fgn_session_get_metrics(fgn_session_handle handle,
                                            fgn_session_metrics* metrics,
                                            uint32_t metrics_size) noexcept {
    if (!metrics || metrics_size < sizeof(*metrics))
        return FGN_INVALID_ARGUMENT;
    *metrics = {};
    auto* slot = find_slot(handle);
    if (!slot)
        return FGN_INVALID_HANDLE;
    try {
        std::unique_lock lock(slot->mutex, std::try_to_lock);
        if (!lock)
            return FGN_BUSY;
        if (slot->handle != handle || !slot->session)
            return FGN_INVALID_HANDLE;
        auto& session = *slot->session;
        *metrics = session.metrics;
        const auto& state = session.protocol.state;
        metrics->state_allocation_count = state.budget.allocation_count;
        metrics->state_allocated_bytes = state.budget.allocated_bytes;
        metrics->state_bytes = state.budget.used;
        metrics->state_peak_bytes = state.budget.peak;
        metrics->active_resources = state.resource_count();
        metrics->tracked_operations = state.operation_count();
        metrics->closed = session.protocol.closed;
        return FGN_OK;
    } catch (...) {
        return FGN_INTERNAL_ERROR;
    }
}

fgn_status FGN_CALL fgn_session_destroy(fgn_session_handle handle) noexcept {
    auto* slot = find_slot(handle);
    if (!slot)
        return FGN_INVALID_HANDLE;
    try {
        std::lock_guard lock(slot->mutex);
        if (slot->handle != handle || !slot->session)
            return FGN_INVALID_HANDLE;
        slot->session.reset();
        slot->handle = 0;
        slot->reserved.store(false);
        return FGN_OK;
    } catch (...) {
        return FGN_INTERNAL_ERROR;
    }
}
