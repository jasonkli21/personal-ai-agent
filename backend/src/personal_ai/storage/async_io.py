"""Run bounded synchronous storage work without blocking the async request loop."""

import asyncio
from functools import partial

import anyio


async def io_call(function, *args, **kwargs):
    """Finish an in-flight write before cancellation can begin compensating work.

    Cancelling an awaiting coroutine cannot cancel its worker thread. Waiting
    for that thread avoids racing a late write with cleanup or a retry. The
    called operation must supply its own finite RPC deadline.
    """
    task = asyncio.create_task(anyio.to_thread.run_sync(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await task
        raise


async def sync_call(function, *args, **kwargs):
    """Run bounded synchronous work off-loop and drain it before cancellation returns.

    The function must bound any external I/O itself. Draining prevents a timed-out
    worker from continuing into a later provider dispatch or storage write.
    """
    task = asyncio.create_task(anyio.to_thread.run_sync(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await task
        raise
