# 06 - Human-in-the-Loop Approval Agent

> Pause on risk, wait for a person, resume with an audit trail.

**What it demonstrates:** Gating irreversible actions behind human approval, durably

**Status:** working implementation with passing tests. Built as a learning project to understand the pattern, not as a production service.

---

## Run it right now

No API key needed - every project ships with `MODEL=fake`, a deterministic
offline responder, so you can see the whole flow work before spending anything.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
python -m src.main
pytest -q
```

To use a real model, edit `.env`:

```
MODEL=gpt-4o-mini            # + OPENAI_API_KEY
MODEL=claude-3-5-haiku-latest  # + ANTHROPIC_API_KEY
MODEL=ollama/llama3.1        # free, runs locally
```

The demo pauses on an irreversible action. Approve it with:

```bash
python -m src.approve <run_id> approve you@example.com
```

## How it works

The agent proposes one action at a time as a validated Pydantic object. `needs_approval()` decides on explicit rules - the action is irreversible, confidence is below the floor, or the cost exceeds the ceiling - rather than on model judgement.

A proposal that needs approval is checkpointed to `.state/<run_id>.json` and the run stops. The process can be killed at that point; `RunState.load()` brings it back. `resume()` applies approve, reject, or edit-and-approve, executes only when approved, and appends an immutable record to `audit.jsonl` either way.

An approval that sits unanswered past its TTL is denied, not executed - the safe default.

## What "done" means here

- Interrupts fire on explicit rules, not model discretion
- State is checkpointed to disk and can be reloaded in a new process
- Approve, reject and edit-and-approve are all supported
- Rejected proposals are never executed
- Every decision appends to an append-only audit log
- An expired approval defaults to denial

Every one of those lines has a test behind it in `tests/` - `pytest -q` is the
proof, not the README.

## Layout

```
src/llm.py             provider-agnostic completion, plus offline fake mode
src/fake.py            the canned responses that make MODEL=fake work
src/logging_setup.py   structured JSON logging
src/agent.py           the pattern itself
src/main.py            CLI entrypoint
src/approve.py         CLI to approve, reject or edit a paused run
tests/                 12 tests, all passing
```

## Next steps

- Require two distinct approvers for the highest-risk actions
- Move the queue from files to Postgres so several workers can share it
- Notify approvers over Slack or email instead of waiting for a CLI

## Reference

https://docs.bswen.com/blog/2026-04-16-langgraph-human-in-the-loop

---

Part of a 12-project agentic AI series - [github.com/dhanashalini25](https://github.com/dhanashalini25?tab=repositories)
