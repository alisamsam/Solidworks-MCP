"""Progress reporting from tool handlers without passing a context through every call.

A handler calls report_progress(); the server installs a reporter for the
current tool call with progress_scope(). Without a reporter the call is a no-op,
so handlers work the same in tests, scripts and clients without progress tokens.
"""

import logging
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger("SolidWorksMCP")

MIN_INTERVAL_S = 0.5
_state = threading.local()


@contextmanager
def progress_scope(reporter):
    """Route report_progress() on this thread to reporter(progress, total, message)."""
    previous = getattr(_state, "scope", None)
    _state.scope = {"reporter": reporter, "last": None} if reporter is not None else None
    try:
        yield
    finally:
        _state.scope = previous


def report_progress(progress, total=None, message=None, *, clock=time.monotonic) -> None:
    """Report progress; at most one update per MIN_INTERVAL_S, the final one always."""
    scope = getattr(_state, "scope", None)
    if scope is None:
        return
    now = clock()
    final = total is not None and progress >= total
    if not final and scope["last"] is not None and now - scope["last"] < MIN_INTERVAL_S:
        return
    scope["last"] = now
    try:
        scope["reporter"](progress, total, message)
    except Exception as error:
        logger.debug(f"Progress report dropped: {error}")
