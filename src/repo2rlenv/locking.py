"""Process locks for controller receipts and shared worker checkouts."""

from __future__ import annotations

import errno
import sys
import time
from typing import IO


def lock_file(handle: IO, *, blocking: bool = False) -> None:
    """Exclusively lock an open file until it closes, without deleting its path.

    POSIX retains flock semantics, including interoperability with older
    controllers. Windows locks byte zero; the region may extend beyond EOF,
    so an empty lock file needs no write. All callers must keep the same path
    and close their handle on success, failure or cancellation.
    """
    if sys.platform != "win32":
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return

    import msvcrt

    handle.seek(0)
    while True:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            if not blocking:
                raise BlockingIOError(errno.EAGAIN, "Another process owns this lock") from error
            # LK_LOCK gives up after ten retries; match flock's indefinite wait.
            time.sleep(0.1)
