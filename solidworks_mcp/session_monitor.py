"""Long-session watch: open/close counts and graphics memory after each tool.

SolidWorks keeps the graphics memory of closed document windows until it
exits (see tools/session.py). The monitor turns that into a warning in the
tool result, so the model can ask the user to save and restart. It never
restarts SolidWorks itself.
"""

import time

from .comutil import com

GPU_WARN_MB = 4096
CLOSED_WARN = 200
GPU_SAMPLE_INTERVAL_S = 60
WARN_INTERVAL_S = 900
LIFECYCLE_TOOLS = frozenset({
    "create_new_part",
    "create_new_assembly",
    "open_document",
    "close_document",
    "restart_solidworks",
    "close_saved_outputs",
})


def _read_pid(sw):
    from .tools.session import solidworks_process_id

    return solidworks_process_id(sw)


def _read_gpu_mb(sw):
    from .tools.session import dedicated_gpu_mb, solidworks_process_id

    return dedicated_gpu_mb(solidworks_process_id(sw))


class SessionMonitor:
    def __init__(self, clock=time.monotonic, gpu_reader=_read_gpu_mb, pid_reader=_read_pid):
        self._clock = clock
        self._gpu_reader = gpu_reader
        self._pid_reader = pid_reader
        self.reset()

    def reset(self) -> None:
        self._pid = None
        self._opened = 0
        self._closed = 0
        self._last_count = None
        self._gpu_mb = None
        self._last_sample = None
        self._last_warning = None

    def observe(self, sw, tool_name: str, succeeded: bool) -> tuple:
        """Update counters after one tool call; return warnings for its result."""
        if tool_name == "restart_solidworks" and succeeded:
            self.reset()
            return ()
        if not getattr(sw, "is_connected", False):
            return ()
        pid = self._pid_reader(sw)
        if pid is not None:
            if self._pid is not None and pid != self._pid:
                self.reset()  # SolidWorks was restarted outside restart_solidworks
            self._pid = pid
        count = int(com(sw.app, "GetDocumentCount"))
        if self._last_count is not None:
            delta = count - self._last_count
            if delta > 0:
                self._opened += delta
            else:
                self._closed -= delta
        self._last_count = count
        now = self._clock()
        if (
            tool_name in LIFECYCLE_TOOLS
            or self._last_sample is None
            or now - self._last_sample >= GPU_SAMPLE_INTERVAL_S
        ):
            self._gpu_mb = self._gpu_reader(sw)
            self._last_sample = now
        return self._warnings(now)

    def _warnings(self, now) -> tuple:
        reasons = []
        if self._gpu_mb is not None and self._gpu_mb >= GPU_WARN_MB:
            reasons.append(f"GPU memory {self._gpu_mb:.0f} MB")
        if self._closed >= CLOSED_WARN:
            reasons.append(f"{self._closed} documents closed")
        if not reasons:
            return ()
        if self._last_warning is not None and now - self._last_warning < WARN_INTERVAL_S:
            return ()
        self._last_warning = now
        return (f"Long SolidWorks session: {', '.join(reasons)}. Save the work and ask the "
                "user before calling restart_solidworks.",)

    def snapshot(self) -> dict:
        return {
            "documents_opened": self._opened,
            "documents_closed": self._closed,
            "gpu_dedicated_mb": self._gpu_mb,
        }


monitor = SessionMonitor()
