"""No POSIX-only stdlib module is imported unconditionally at module level.

`fcntl` (and pwd/grp/termios/tty/pty/posix/resource/crypt/nis/spwd) don't
exist on Windows. An unconditional `import fcntl` at the top of a module
crashes with `ModuleNotFoundError` the moment anything imports that module —
even just to register an argparse subcommand, never to call anything
POSIX-specific. `cli.py`'s dispatcher eagerly imports every subsystem just to
build `--help`, so one such import anywhere in that chain took down
`repo2rlenv --version` entirely (#128). CI runs on Linux only, where these
modules exist, so the bug is invisible there — this static check keeps new
top-level imports explicit about the platforms they need.

Guard the import instead: `if sys.platform != "win32": import fcntl`.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import repo2rlenv

SRC = Path(repo2rlenv.__file__).parent

_POSIX_ONLY = frozenset(
    {"fcntl", "pwd", "grp", "termios", "tty", "pty", "posix", "resource", "crypt", "nis", "spwd"}
)


def _unconditional_posix_only_imports() -> Iterator[str]:
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Only module.body (top level): an import inside an `if` guard, e.g.
        # `if sys.platform != "win32": import fcntl`, is intentionally exempt.
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _POSIX_ONLY:
                        where = f"{path.relative_to(SRC).as_posix()}:{node.lineno}"
                        yield f"{where} (import {alias.name})"
            elif isinstance(node, ast.ImportFrom) and node.module in _POSIX_ONLY:
                where = f"{path.relative_to(SRC).as_posix()}:{node.lineno}"
                yield f"{where} (from {node.module} import ...)"


def test_no_unconditional_posix_only_imports():
    offenders = list(_unconditional_posix_only_imports())
    assert offenders == [], (
        f'guard with `if sys.platform != "win32":` before importing: {offenders}'
    )
