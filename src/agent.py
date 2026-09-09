"""Human-in-the-Loop Approval Agent - pause, wait for a person, resume.

Risky proposals interrupt the run and checkpoint to disk. The process can die;
`RunState.load` brings it back. Every decision appends to an immutable audit
log, and a pending approval that ages out is denied, not silently executed.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .llm import complete
from .logging_setup import log, safe_extra

STATE_DIR = Path(".state")
AUDIT_LOG = Path("audit.jsonl")
CONFIDENCE_FLOOR = 0.7
COST_CEILING_USD = 1.00
APPROVAL_TTL = timedelta(hours=4)
DEMO = "Email the whole customer list about tomorrow's outage."

IRREVERSIBLE = {"send_email", "delete_records", "charge_card", "deploy"}


class Proposal(BaseModel):
    action: str
    args: dict = Field(default_factory=dict)
    rationale: str = ""
    confidence: float = Field(ge=0, le=1, default=1.0)
    est_cost: float = Field(ge=0, default=0.0)


@dataclass
class Pending:
    proposal: dict
    created_at: str
    status: str = "pending"
    decided_by: str | None = None
    decided_at: str | None = None


@dataclass
class RunState:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    task: str = ""
    pending: Pending | None = None
    result: str | None = None

    # ------------------------------------------------------- persistence
    def path(self) -> Path:
        return STATE_DIR / f"{self.run_id}.json"

    def save(self) -> "RunState":
        STATE_DIR.mkdir(exist_ok=True)
        self.path().write_text(json.dumps(asdict(self)), encoding="utf-8")
        return self

    @classmethod
    def load(cls, run_id: str) -> "RunState":
        raw = json.loads((STATE_DIR / f"{run_id}.json").read_text(encoding="utf-8"))
        pending = Pending(**raw.pop("pending")) if raw.get("pending") else None
        return cls(**{**raw, "pending": pending})


def audit(event: str, **fields) -> dict:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    log.info(event, extra=safe_extra(fields))
    return record


def needs_approval(p: Proposal) -> bool:
    return (
        p.action in IRREVERSIBLE
        or p.confidence < CONFIDENCE_FLOOR
        or p.est_cost > COST_CEILING_USD
    )


def expired(pending: Pending, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return now - datetime.fromisoformat(pending.created_at) > APPROVAL_TTL


# ------------------------------------------------------------- actions
def _send_email(to: str = "", subject: str = "", **_) -> str:
    return f"email sent to {to or 'nobody'} - {subject!r}"


def _read_docs(query: str = "", **_) -> str:
    return f"read docs matching {query!r}"


ACTIONS = {"send_email": _send_email, "read_docs": _read_docs}

SYSTEM = (
    "Decide the single next action. Reply with ONE JSON object:\n"
    '{"action": "send_email|read_docs", "args": {...}, "rationale": "...", '
    '"confidence": 0.0-1.0, "est_cost": 0.0}'
)


def propose(task: str) -> Proposal:
    raw = complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}])
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        return Proposal.model_validate_json(match.group(0) if match else raw)
    except (ValidationError, ValueError, AttributeError) as err:
        log.warning("proposal_invalid", extra={"error": str(err)[:200]})
        return Proposal(action="read_docs", args={"query": task}, rationale="fallback",
                        confidence=0.3)


def execute(p: Proposal) -> str:
    fn = ACTIONS.get(p.action)
    if not fn:
        return f"unknown action: {p.action}"
    return fn(**p.args)


def start(task: str) -> RunState:
    """Run until either done or blocked on a human."""
    state = RunState(task=task)
    p = propose(task)

    if needs_approval(p):
        state.pending = Pending(
            proposal=p.model_dump(), created_at=datetime.now(timezone.utc).isoformat()
        )
        state.save()
        audit("interrupt", run_id=state.run_id, action=p.action, confidence=p.confidence)
        return state

    state.result = execute(p)
    state.save()
    audit("auto_executed", run_id=state.run_id, action=p.action)
    return state


def resume(state: RunState, decision: str, actor: str, edits: dict | None = None) -> RunState:
    """Apply a human decision. decision is approve | reject | edit."""
    if not state.pending:
        raise ValueError("nothing pending on this run")

    if expired(state.pending):
        state.pending.status = "rejected"
        state.pending.decided_by = "system:timeout"
        state.pending.decided_at = datetime.now(timezone.utc).isoformat()
        state.result = "denied: approval expired"
        state.save()
        audit("timeout_denied", run_id=state.run_id)
        return state

    p = Proposal(**state.pending.proposal)
    if decision == "edit":
        p = p.model_copy(update={"args": {**p.args, **(edits or {})}})
        state.pending.proposal = p.model_dump()
        decision_label = "edited"
    elif decision == "approve":
        decision_label = "approved"
    else:
        decision_label = "rejected"

    state.pending.status = decision_label
    state.pending.decided_by = actor
    state.pending.decided_at = datetime.now(timezone.utc).isoformat()
    state.result = execute(p) if decision in {"approve", "edit"} else "rejected by " + actor
    state.save()
    audit("decision", run_id=state.run_id, decision=decision_label, actor=actor,
          action=p.action, args=p.args)
    return state


def run(prompt: str) -> str:
    state = start(prompt)
    if not state.pending:
        return f"auto-executed: {state.result}"
    p = state.pending.proposal
    return (
        f"PAUSED for approval\n"
        f"  run id   : {state.run_id}\n"
        f"  action   : {p['action']}({p['args']})\n"
        f"  why      : {p['rationale']}\n"
        f"  approve  : python -m src.approve {state.run_id} approve you@example.com\n"
        f"  reject   : python -m src.approve {state.run_id} reject you@example.com"
    )
