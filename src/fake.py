"""Canned proposal for MODEL=fake - an irreversible action, so it pauses."""
from __future__ import annotations


def respond(messages: list[dict]) -> str:
    task = messages[-1]["content"].lower()
    if "email" in task:
        return (
            '{"action": "send_email", '
            '"args": {"to": "customers@example.com", "subject": "Planned outage"}, '
            '"rationale": "The user asked to notify the customer list.", '
            '"confidence": 0.82, "est_cost": 0.02}'
        )
    return (
        '{"action": "read_docs", "args": {"query": "outage policy"}, '
        '"rationale": "Read-only lookup.", "confidence": 0.95, "est_cost": 0.0}'
    )
