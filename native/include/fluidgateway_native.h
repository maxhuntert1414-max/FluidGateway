#ifndef FLUIDGATEWAY_NATIVE_H
#define FLUIDGATEWAY_NATIVE_H

#include <stdint.h>

#if defined(_WIN32)
#if defined(FLUIDGATEWAY_BUILD_DLL)
#define FGN_API __declspec(dllexport)
#else
#define FGN_API __declspec(dllimport)
#endif
#define FGN_CALL __cdecl
#else
#define FGN_API
#define FGN_CALL
#endif

#ifdef __cplusplus
#define FGN_NOEXCEPT noexcept
extern "C" {
#else
#define FGN_NOEXCEPT
#endif

#define FGN_ABI_VERSION UINT32_C(0x00010000)
#define FGN_MAX_FRAME_BYTES UINT32_C(65591)
#define FGN_MAX_SESSIONS UINT32_C(8)
#define FGN_FEATURE_FLUIDLINK_V2 UINT64_C(1)
#define FGN_FEATURE_OPERATION_BATCH UINT64_C(2)

typedef uint64_t fgn_session_handle;
typedef uint32_t fgn_status;

#define FGN_OK UINT32_C(0)
#define FGN_INVALID_ARGUMENT UINT32_C(1)
#define FGN_ABI_MISMATCH UINT32_C(2)
#define FGN_INVALID_HANDLE UINT32_C(3)
#define FGN_LIMIT_REACHED UINT32_C(4)
#define FGN_BUFFER_TOO_SMALL UINT32_C(5)
#define FGN_SESSION_CLOSED UINT32_C(6)
#define FGN_INVALID_FRAME UINT32_C(7)
#define FGN_OUT_OF_MEMORY UINT32_C(8)
#define FGN_INTERNAL_ERROR UINT32_C(9)
#define FGN_BUSY UINT32_C(10)

typedef struct fgn_abi_info {
    uint32_t abi_version;
    uint32_t struct_size;
    uint32_t max_frame_bytes;
    uint32_t max_sessions;
    uint32_t max_resources;
    uint32_t max_operations;
    uint64_t max_state_bytes;
    uint64_t features;
} fgn_abi_info;

/* Allocation counters cover retained PMR state, not all CRT/codec allocations.
 * Copy counters cover explicit request/response payload copies at the wire codec,
 * not header fields, STL internals, caller copies or operating-system traffic. */
typedef struct fgn_session_metrics {
    uint64_t exchanges;
    uint64_t request_bytes;
    uint64_t response_bytes;
    uint64_t wire_payload_copy_bytes;
    uint64_t wire_payload_copy_count;
    uint64_t state_allocation_count;
    uint64_t state_allocated_bytes;
    uint64_t state_bytes;
    uint64_t state_peak_bytes;
    uint64_t active_resources;
    uint64_t tracked_operations;
    uint32_t closed;
    uint32_t reserved;
} fgn_session_metrics;

FGN_API fgn_status FGN_CALL fgn_get_abi_info(uint32_t requested_version,
                                             fgn_abi_info* info,
                                             uint32_t info_size) FGN_NOEXCEPT;

/* Handles are opaque, generation-tagged tokens, never dereferenceable pointers.
 * A module permits at most eight live sessions. Each new session must handshake. */
FGN_API fgn_status FGN_CALL fgn_session_create(uint32_t requested_version,
                                               fgn_session_handle* session) FGN_NOEXCEPT;

/* One complete v2 frame per call. Buffers and output_size must be valid, writable
 * where applicable, and non-overlapping. Pointers are borrowed only for this call.
 * Require FGN_MAX_FRAME_BYTES capacity before consuming any request. Too-small
 * buffers return that capacity in output_size, with no state/sequence change.
 * FGN_OK means a complete response; inspect its v2 OK/error flag separately.
 * Framing/allocation/internal failures retire the session and return no response.
 * Concurrent exchanges on the same handle may return FGN_BUSY without mutation. */
FGN_API fgn_status FGN_CALL fgn_session_exchange(fgn_session_handle session,
                                                 const uint8_t* request,
                                                 uint32_t request_size,
                                                 uint8_t* output,
                                                 uint32_t output_capacity,
                                                 uint32_t* output_size) FGN_NOEXCEPT;

FGN_API fgn_status FGN_CALL fgn_session_get_metrics(fgn_session_handle session,
                                                    fgn_session_metrics* metrics,
                                                    uint32_t metrics_size) FGN_NOEXCEPT;

/* Waits for an active exchange, then releases the state. Later/stale calls fail.
 * Sessions must be destroyed before unloading the DLL. The ABI catches C++
 * exceptions, not access violations caused by invalid caller memory or bugs. */
FGN_API fgn_status FGN_CALL fgn_session_destroy(fgn_session_handle session) FGN_NOEXCEPT;

#ifdef __cplusplus
}
#endif
#endif
