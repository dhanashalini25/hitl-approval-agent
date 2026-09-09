import json
from datetime import datetime, timedelta, timezone

import pytest

from src import agent
from src.agent import (
    IRREVERSIBLE, Pending, Proposal, RunState, expired, needs_approval, resume, start,
)

SAFE = '{"action": "read_docs", "args": {"query": "x"}, "confidence": 0.95, "est_cost": 0.0}'
RISKY = '{"action": "send_email", "args": {"to": "a@b.c"}, "confidence": 0.9, "est_cost": 0.0}'


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(agent, "AUDIT_LOG", tmp_path / "audit.jsonl")


def test_irreversible_needs_approval():
    assert needs_approval(Proposal(action=sorted(IRREVERSIBLE)[0], confidence=1.0))


def test_low_confidence_needs_approval():
    assert needs_approval(Proposal(action="read_docs", confidence=0.2))


def test_expensive_needs_approval():
    assert needs_approval(Proposal(action="read_docs", confidence=1.0, est_cost=5.0))


def test_safe_action_runs_unattended(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: SAFE)
    state = start("look something up")
    assert state.pending is None and "read docs" in state.result


def test_risky_action_pauses(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: RISKY)
    state = start("email everyone")
    assert state.pending and state.pending.status == "pending"


def test_checkpoint_round_trips(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: RISKY)
    state = start("email everyone")
    reborn = RunState.load(state.run_id)
    assert reborn.pending.proposal["action"] == "send_email"
    assert reborn.task == "email everyone"


def test_approve_executes(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: RISKY)
    state = resume(start("email everyone"), "approve", "dhana@example.com")
    assert state.pending.status == "approved"
    assert "email sent" in state.result


def test_reject_does_not_execute(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: RISKY)
    state = resume(start("email everyone"), "reject", "dhana@example.com")
    assert state.pending.status == "rejected"
    assert "email sent" not in state.result


def test_edit_then_approve(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: RISKY)
    state = resume(start("email everyone"), "edit", "dhana@example.com", {"to": "team@x.com"})
    assert "team@x.com" in state.result


def test_expired_approval_is_denied(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: RISKY)
    state = start("email everyone")
    state.pending.created_at = (
        datetime.now(timezone.utc) - timedelta(days=2)
    ).isoformat()
    state = resume(state, "approve", "dhana@example.com")
    assert state.result.startswith("denied")
    assert state.pending.decided_by == "system:timeout"


def test_audit_log_is_append_only(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: RISKY)
    resume(start("email everyone"), "approve", "dhana@example.com")
    lines = agent.AUDIT_LOG.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["interrupt", "decision"]


def test_invalid_proposal_falls_back_safely(monkeypatch):
    monkeypatch.setattr(agent, "complete", lambda m, **k: "I'm not sure what to do")
    assert start("something").pending is not None  # low confidence -> paused
