from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Optional


class SyncLockError(RuntimeError):
    """Raised when a sync lock cannot be acquired or released cleanly."""


class SyncLock:
    """
    Simple file-based lock using O_CREAT|O_EXCL.
    - Creates a lock file atomically. Fails if it already exists.
    - Detects and breaks stale locks (mtime older than stale_after).
    - Writes pid/timestamp into the file for observability.
    """

    def __init__(self, lock_path: Path, stale_after: int = 3600):
        self.lock_path = Path(lock_path)
        self.stale_after = stale_after
        self._acquired = False
        self._pid = os.getpid()

    def _is_stale(self) -> bool:
        try:
            stat = self.lock_path.stat()
        except FileNotFoundError:
            return False
        age = time.time() - stat.st_mtime
        return age > self.stale_after

    def _break_stale(self) -> None:
        try:
            self.lock_path.unlink(missing_ok=True)
        except Exception as e:
            raise SyncLockError(f"Failed to break stale lock: {e}") from e

    def __enter__(self) -> "SyncLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        # If a previous lock exists and is stale, try to break it.
        if self.lock_path.exists() and self._is_stale():
            self._break_stale()

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(self.lock_path), flags, 0o644)
        except FileExistsError:
            # Another process holds the lock (not stale)
            raise SyncLockError("locked")

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                now = int(time.time())
                f.write(f"pid={self._pid}\n")
                f.write(f"ts={now}\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            # Clean up partially created lock file
            try:
                self.lock_path.unlink(missing_ok=True)
            finally:
                raise

        self._acquired = True
        return self

    def __exit__(self, exc_type, exc, tb) -> Optional[bool]:
        if self._acquired:
            try:
                self.lock_path.unlink(missing_ok=True)
            except Exception as e:
                raise SyncLockError(f"Failed to release lock: {e}") from e
        self._acquired = False
        # Do not suppress exceptions
        return None
