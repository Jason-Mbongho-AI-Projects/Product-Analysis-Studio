"""Monitor scheduler (spec 33).

Closes the loop on continuous intelligence: monitors already know when they are
due, but nothing woke the process to run them. This is a single daemon thread
that periodically asks for due monitors and dispatches them.

Deliberately modest. It runs only while the app process is alive, which suits a
locally-run product; a server deployment would point cron or systemd at
``run_due_monitors`` instead. That function is the whole contract, so swapping
the trigger later touches nothing else.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: How often to look for due monitors. Monitors run on multi-hour intervals, so
#: checking every few minutes is ample and costs nothing when nothing is due.
DEFAULT_TICK_SECONDS = 300

#: Never dispatch more than this many monitors in one tick, so a backlog after a
#: long shutdown cannot stampede the model provider.
MAX_PER_TICK = 3


@dataclass
class SchedulerState:
    started_at: float = field(default_factory=time.time)
    last_tick_at: float | None = None
    ticks: int = 0
    dispatched: int = 0
    errors: int = 0
    last_error: str | None = None
    running: bool = False


class MonitorScheduler:
    """Periodically dispatches monitors whose interval has elapsed."""

    def __init__(
        self,
        due_provider: Callable[[], list[dict[str, Any]]],
        dispatch: Callable[[str], Any],
        *,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        max_per_tick: int = MAX_PER_TICK,
    ) -> None:
        self._due_provider = due_provider
        self._dispatch = dispatch
        self._tick_seconds = tick_seconds
        self._max_per_tick = max_per_tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = SchedulerState()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.state = SchedulerState(running=True)
        self._thread = threading.Thread(
            target=self._loop, name="pas-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self.state.running = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            # Wait first so startup is never blocked by a tick.
            if self._stop.wait(self._tick_seconds):
                break
            self.tick()

    def tick(self) -> int:
        """Run one scheduling pass. Returns how many monitors were dispatched.

        Exposed separately from the loop so it can be tested directly and
        triggered manually from the diagnostics page.
        """
        self.state.ticks += 1
        self.state.last_tick_at = time.time()

        try:
            due = self._due_provider()
        except Exception as exc:  # a scheduler must not die on one bad query
            self.state.errors += 1
            self.state.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Scheduler could not list due monitors: %s", exc)
            return 0

        dispatched = 0
        for monitor in due[: self._max_per_tick]:
            try:
                self._dispatch(monitor["id"])
                dispatched += 1
            except Exception as exc:
                self.state.errors += 1
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Monitor %s failed to dispatch: %s", monitor.get("id"), exc)

        self.state.dispatched += dispatched
        return dispatched


_scheduler: MonitorScheduler | None = None
_lock = threading.Lock()


def get_scheduler() -> MonitorScheduler | None:
    return _scheduler


def start_scheduler(
    due_provider: Callable[[], list[dict[str, Any]]],
    dispatch: Callable[[str], Any],
    *,
    tick_seconds: float = DEFAULT_TICK_SECONDS,
) -> MonitorScheduler:
    """Start the process-wide scheduler, or return the running one."""
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = MonitorScheduler(
                due_provider, dispatch, tick_seconds=tick_seconds
            )
            _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    with _lock:
        if _scheduler is not None:
            _scheduler.stop()
            _scheduler = None
