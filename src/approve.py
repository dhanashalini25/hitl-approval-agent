"""Approve, reject or edit a paused run.

    python -m src.approve <run_id> approve you@example.com
    python -m src.approve <run_id> edit    you@example.com to=team@example.com
"""
from __future__ import annotations

import sys

from .agent import RunState, resume

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(1)

    run_id, decision, actor = sys.argv[1:4]
    edits = dict(pair.split("=", 1) for pair in sys.argv[4:] if "=" in pair)

    state = resume(RunState.load(run_id), decision, actor, edits or None)
    print(f"{state.pending.status} by {state.pending.decided_by}")
    print(f"result: {state.result}")
