#include "fluidgateway_native.h"
#include <stddef.h>

_Static_assert(sizeof(fgn_session_handle) == 8, "handle width");
_Static_assert(sizeof(fgn_abi_info) == 40, "ABI info layout");
_Static_assert(offsetof(fgn_abi_info, max_state_bytes) == 24, "ABI alignment");
_Static_assert(sizeof(fgn_session_metrics) == 96, "metrics layout");

int main(void) {
    fgn_abi_info info = {0};
    fgn_session_handle handle = 0;
    fgn_session_metrics metrics = {0};
    if (fgn_get_abi_info(FGN_ABI_VERSION, &info, sizeof(info)) != FGN_OK ||
        info.max_sessions != 8 || info.max_frame_bytes != 65591 ||
        info.max_state_bytes != 8388608 || info.features != 3)
        return 1;
    if (fgn_session_create(FGN_ABI_VERSION, &handle) != FGN_OK || !handle)
        return 2;
    if (fgn_session_get_metrics(handle, &metrics, sizeof(metrics)) != FGN_OK || metrics.exchanges ||
        metrics.closed)
        return 3;
    if (fgn_session_destroy(handle) != FGN_OK || fgn_session_destroy(handle) != FGN_INVALID_HANDLE)
        return 4;
    return 0;
}
