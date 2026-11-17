"""Internal file, naming and rate-limiting helpers shared across modules."""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Callable

try:  # pragma: no cover - availability is platform dependent
    import fcntl
except ImportError:  # non-POSIX: cross-process coordination is disabled
    fcntl = None  # type: ignore[assignment]

DEFAULT_SLEEP_S = 3.0

__all__ = [
    "DEFAULT_SLEEP_S",
    "OkfError",
    "RateLimiter",
    "_atomic_write",
    "_safe_name",
]


class OkfError(Exception):
    """Base exception for OKF errors."""


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return cleaned or hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def _atomic_write(path: Path, data: str | bytes, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        if isinstance(data, bytes):
            tmp.write_bytes(data)
        else:
            tmp.write_text(data, encoding="utf-8")
        if private:
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class RateLimiter:
    """Minimum interval between network requests.

    In-process spacing uses a monotonic clock. When ``state_path`` is given
    (and ``fcntl`` is available), the same interval is enforced *across
    processes*: the timestamp of the last OPS request is stored in a small
    file and requests serialize on an exclusive lock, so running several
    scripts in parallel never removes the spacing. Coordination is best
    effort and never raises.
    """

    def __init__(self, min_interval: float = DEFAULT_SLEEP_S,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep,
                 state_path: str | Path | bool | None = None,
                 wall: Callable[[], float] = time.time):
        self.min_interval = max(0.0, float(min_interval))
        self._clock = clock
        self._sleep = sleeper
        self._last: float | None = None
        if state_path and fcntl is not None:
            self.state_path = Path(state_path)
        else:
            self.state_path = None
        self._wall = wall

    def _wait_in_process(self) -> None:
        if self._last is not None:
            delay = self.min_interval - (self._clock() - self._last)
            if delay > 0:
                self._sleep(delay)
        self._last = self._clock()

    def _wait_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.state_path, os.O_RDWR | os.O_CREAT)
            with os.fdopen(descriptor, "r+") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    last = 0.0
                    raw = handle.read().strip()
                    if raw:
                        try:
                            last = float(raw)
                        except ValueError:
                            last = 0.0
                    # Clamp so a skewed clock cannot stall the caller.
                    delay = min(self.min_interval - (self._wall() - last),
                                self.min_interval)
                    if delay > 0:
                        # Sleep while holding the lock: this serializes
                        # concurrent processes and preserves the interval.
                        self._sleep(delay)
                    handle.seek(0)
                    handle.truncate()
                    handle.write(f"{self._wall():.6f}\n")
                    handle.flush()
                    self._last = self._clock()
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            self._wait_in_process()
        except ValueError:
            return

    def wait(self) -> None:
        if self.state_path is not None:
            self._wait_state()
            return
        self._wait_in_process()
