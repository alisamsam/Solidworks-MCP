"""One single-threaded apartment thread that owns every SolidWorks COM call.

COM objects from SolidWorks are apartment-bound: the thread that connected
must make every later call. Running tools here keeps the asyncio event loop
free for pings, cancellations and progress notifications.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor


def _initialize_com() -> None:
    import pythoncom

    pythoncom.CoInitialize()


_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="solidworks-com",
    initializer=_initialize_com,
)


async def run_beside_com(fn, *args):
    """Run fn(*args) in a worker thread, for tools that never touch COM."""
    return await asyncio.to_thread(fn, *args)


async def run_com(fn, *args):
    """Run fn(*args) on the COM thread and await its result."""
    return await asyncio.get_running_loop().run_in_executor(_executor, fn, *args)
