"""Run the no-game match lifecycle from the command line.

    python tests/simulate_match_lifecycle.py

It starts the real Tk overlay briefly, feeds the real advisor and worker poll
path with early, mid, late, ended and restarted match states, prints the
observed rows, and exits non-zero if any assertion fails.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from match_lifecycle_sim import run  # noqa: E402


def main() -> int:
    try:
        report = run(verbose=True)
    except RuntimeError as err:
        if "Tk unavailable" in str(err):
            print(f"SIMULATION SKIPPED: {err}")
            return 2
        raise
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
