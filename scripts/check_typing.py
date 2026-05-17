"""Run the scoped static type-checking gate."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Run mypy with repository configuration."""
    if importlib.util.find_spec("mypy") is None:
        print(
            "ERROR: mypy is not installed. Install it with "
            "`python -m pip install 'mypy>=1.13,<2'`.",
            file=sys.stderr,
        )
        return 1
    return subprocess.run(
        [sys.executable, "-m", "mypy"],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
