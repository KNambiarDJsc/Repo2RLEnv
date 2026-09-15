"""Exercise real OS locks between independent processes, including on Windows."""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from repo2rlenv.locking import lock_file

_OWNER = """
import sys
from repo2rlenv.locking import lock_file
with open(sys.argv[1], 'a') as handle:
    lock_file(handle)
    sys.stdout.write('locked\\n')
    sys.stdout.flush()
    sys.stdin.read()
"""


def _line(process: subprocess.Popen) -> str:
    with ThreadPoolExecutor(max_workers=1) as reader:
        ready = reader.submit(process.stdout.readline)
        try:
            return ready.result(timeout=15)
        except BaseException:
            process.kill()
            raise


@contextmanager
def _owner(path: Path, code: str = _OWNER):
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # A bounded handshake avoids a hanging test if the child cannot import.
        assert _line(process) == "locked\n"
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=15)


def test_nonblocking_lock_and_release(tmp_path):
    path = tmp_path / "controller.lock"
    with _owner(path) as owner:
        with path.open("a") as handle, pytest.raises(BlockingIOError):
            lock_file(handle)
        owner.communicate(timeout=15)
        assert owner.returncode == 0
    with path.open("a") as handle:
        lock_file(handle)
    assert path.read_bytes() == b""  # An empty lock file needs no mutation.


def test_lock_released_after_process_death(tmp_path):
    path = tmp_path / "controller.lock"
    with _owner(path) as owner:
        owner.kill()
        owner.communicate(timeout=15)
    with path.open("a") as handle:
        lock_file(handle)


def test_blocking_lock_waits_for_owner(tmp_path):
    path = tmp_path / "checkout.lock"
    contender_code = _OWNER.replace("lock_file(handle)", "lock_file(handle, blocking=True)")
    contender_code = contender_code.replace(
        "    lock_file(handle, blocking=True)",
        "    sys.stdout.write('attempting\\n')\n"
        "    sys.stdout.flush()\n"
        "    lock_file(handle, blocking=True)",
    )
    contender_code = contender_code.replace("    sys.stdin.read()", "")
    with _owner(path) as owner:
        contender = subprocess.Popen(
            [sys.executable, "-c", contender_code, str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert _line(contender) == "attempting\n"
            with pytest.raises(subprocess.TimeoutExpired):
                contender.communicate(timeout=0.5)
            owner.communicate(timeout=15)
            stdout, stderr = contender.communicate(timeout=15)
            assert contender.returncode == 0, stderr
            assert stdout == "locked\n"
        finally:
            if contender.poll() is None:
                contender.kill()
            contender.communicate(timeout=15)


@pytest.mark.skipif(sys.platform == "win32", reason="Interoperability with earlier POSIX releases")
def test_interoperates_with_existing_flock(tmp_path):
    path = tmp_path / "controller.lock"
    code = _OWNER.replace("from repo2rlenv.locking import lock_file", "import fcntl")
    code = code.replace("lock_file(handle)", "fcntl.flock(handle, fcntl.LOCK_EX)")
    with _owner(path), path.open("a") as handle, pytest.raises(BlockingIOError):
        lock_file(handle)
