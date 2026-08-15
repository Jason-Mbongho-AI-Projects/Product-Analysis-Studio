"""Background job runner (spec 45).

Analyses take minutes. Running one inside a Streamlit callback would freeze the
session and lose the work on any rerun, so jobs execute on a worker thread and
the UI polls durable state in sqlite.

An in-process thread pool is the right size for a single-user desktop app; the
interface here is narrow enough that swapping in a real queue later would not
disturb callers.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_EVENTS = 400


@dataclass
class JobState:
    """Live state for one running analysis."""

    job_id: str
    analysis_id: str
    status: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_event(self, event: str, message: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(
                {
                    "event": event,
                    "message": message,
                    "payload": payload,
                    "at": time.time(),
                }
            )
            # Bound memory on a long run rather than growing without limit.
            if len(self.events) > MAX_EVENTS:
                del self.events[: len(self.events) - MAX_EVENTS]

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.events)

    @property
    def is_terminal(self) -> bool:
        return self.status in {"succeeded", "failed", "cancelled"}


class JobRunner:
    """Process-wide registry of background analysis jobs."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="pas-job"
        )
        self._jobs: dict[str, JobState] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        job_id: str,
        analysis_id: str,
        work: Callable[[Callable[[str, str, dict], None], threading.Event], Any],
    ) -> JobState:
        """Schedule ``work``, passing it a progress callback and a cancel flag."""
        state = JobState(job_id=job_id, analysis_id=analysis_id)
        with self._lock:
            self._jobs[job_id] = state

        def target() -> Any:
            state.status = "running"
            try:
                result = work(state.add_event, state.cancel_event)
                state.status = "cancelled" if state.cancel_event.is_set() else "succeeded"
                return result
            except Exception as exc:
                state.status = "failed"
                state.error = f"{type(exc).__name__}: {exc}"
                state.add_event("failed", state.error, {})
                return None
            finally:
                state.finished_at = time.time()

        with self._lock:
            self._futures[job_id] = self._executor.submit(target)
        return state

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        state = self.get(job_id)
        if state is None or state.is_terminal:
            return False
        state.cancel_event.set()
        state.add_event("cancel_requested", "Cancellation requested", {})
        return True

    def active_jobs(self) -> list[JobState]:
        with self._lock:
            return [job for job in self._jobs.values() if not job.is_terminal]

    def prune(self, older_than_seconds: float = 3600) -> int:
        """Drop finished jobs so the registry does not grow across a long session."""
        cutoff = time.time() - older_than_seconds
        with self._lock:
            stale = [
                job_id
                for job_id, job in self._jobs.items()
                if job.is_terminal and (job.finished_at or 0) < cutoff
            ]
            for job_id in stale:
                self._jobs.pop(job_id, None)
                self._futures.pop(job_id, None)
        return len(stale)


_runner: JobRunner | None = None
_runner_lock = threading.Lock()


def get_runner() -> JobRunner:
    """Return the process-wide runner.

    Streamlit reruns the script on every interaction, so the runner must live
    at module scope rather than in session state.
    """
    global _runner
    if _runner is None:
        with _runner_lock:
            if _runner is None:
                _runner = JobRunner()
    return _runner
