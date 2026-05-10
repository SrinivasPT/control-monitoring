"""scripts/lint.py — Run ruff linter (and optionally auto-fix) on the project.

Usage:
  python scripts/lint.py              # check only, exit 1 on errors
  python scripts/lint.py --fix        # auto-fix safe issues, then report remainder
  python scripts/lint.py --format     # also run ruff format (style formatting)
  python scripts/lint.py --fix --format
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TARGETS = ["src", "scripts", "run.py", "tests"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lint the project with ruff.")
    p.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe auto-fixes before reporting.",
    )
    p.add_argument(
        "--format",
        action="store_true",
        help="Run ruff format (code style) in addition to lint checks.",
    )
    return p.parse_args()


def run(cmd: list[str]) -> int:
    """Run *cmd* from the project root and return the exit code."""
    result = subprocess.run(cmd, cwd=_ROOT)
    return result.returncode


def main() -> None:
    args = parse_args()
    exit_code = 0

    # --- Lint (ruff check) ---
    check_cmd = [sys.executable, "-m", "ruff", "check"] + _TARGETS
    if args.fix:
        check_cmd.append("--fix")
    exit_code |= run(check_cmd)

    # --- Format (ruff format) ---
    if args.format:
        fmt_mode = [] if args.fix else ["--check"]
        fmt_cmd = [sys.executable, "-m", "ruff", "format"] + fmt_mode + _TARGETS
        exit_code |= run(fmt_cmd)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
