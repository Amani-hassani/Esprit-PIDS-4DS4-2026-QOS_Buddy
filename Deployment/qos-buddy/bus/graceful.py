from __future__ import annotations

import asyncio
import logging
import signal


def install_sigterm_handler(log: logging.Logger) -> None:
    """Cancel the running asyncio tasks so service finally blocks can drain."""
    loop = asyncio.get_running_loop()
    stopping = False

    def _handle(_signum: int, _frame: object | None) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        log.info("SIGTERM received; stopping Redis consumers")
        current = asyncio.current_task(loop)
        for task in asyncio.all_tasks(loop):
            if task is not current:
                task.cancel()

    signal.signal(signal.SIGTERM, _handle)
