"""Persistent, advisory engineering conversations; publication remains a separate gate."""

import json
import time

from forge.llm import Provider
from forge.policy import PolicyError
from forge.store import Conflict


def prepare(store, run_id, message, request_key):
    run = store.get(run_id)
    for turn in run.get("chat", []):
        if turn["id"] == request_key:
            if turn["message"] != message:
                raise Conflict("Chat request key belongs to another message.")
            return run, False

    def begin(row, data):
        turns = data.setdefault("chat", [])
        if any(t["id"] == request_key for t in turns):
            raise Conflict("This message is already being processed. Refresh the conversation.")
        if any(t["status"] == "pending" and time.time() - t["created"] < 900 for t in turns):
            raise Conflict("Wait for Forge's current reply before sending another message.")
        if len(turns) >= 100:
            raise Conflict("This conversation is full. Start a follow-up proposal to continue.")
        for turn in turns:
            if turn["status"] == "pending":
                turn.update(status="failed", error="Reply interrupted. Send your message again.")
        turns.append(dict(id=request_key, message=message, created=time.time(), status="pending"))

    return store.mutate(run_id, begin), True


def reply(store, config, run_id, request_key):
    run = store.get(run_id)
    usage = {"calls": 0, "tokens": 0, "cost": 0, "run_id": run_id}

    def save_usage(value):
        def update(row, data):
            next(t for t in data["chat"] if t["id"] == request_key)["usage"] = value

        store.mutate(run_id, update)

    selected = config.model_copy(deep=True)
    selected.max_calls = 3
    selected.max_tokens = 100000
    selected.max_output_tokens = min(selected.max_output_tokens, 2048)
    context = {
        "latest_message": next(t["message"] for t in run["chat"] if t["id"] == request_key),
        "repository": run["repo"],
        "issue": run["issue"],
        "title": run.get("title"),
        "request": run.get("feedback") or run.get("request"),
        "status": run["status"],
        "error": run.get("error"),
        "execution_model": run.get("model"),
        "connected_model": selected.llm_model,
        "prior_diagnostics": run.get("diagnostics"),
        "plan": run.get("plan"),
        "candidate_diff": str((run.get("candidate") or {}).get("patch", ""))[:12000],
        "checks": [
            {k: str(c.get(k, ""))[-3000:] for k in ("phase", "status", "exit_code", "count", "output")}
            for c in run.get("checks", [])[-2:]
        ],
        "conversation": [
            {"user": t["message"], "assistant": t.get("reply", "")[:2000]} for t in run["chat"][-6:]
        ],
    }
    encoded = json.dumps(context)
    for secret in (config.llm_api_key, config.owner_token):
        if secret:
            encoded = encoded.replace(secret, "[redacted]")
    context = json.loads(encoded)
    answer, error = "", ""
    try:
        result = Provider(selected, usage, save_usage, lambda: store.get(run_id).get("ended", False)).ask(
            "conversation",
            "Answer the owner's latest message as a helpful engineering collaborator. Return JSON with "
            "reply:string. Explain, clarify requirements, discuss improvements and diagnose supplied evidence. "
            "You have only the context supplied here, not access to the complete repository or tools. "
            "Do not claim to execute commands, modify files, install anything or publish changes. "
            "When changes are requested, discuss them and explain that Build from conversation creates "
            "a separately checked proposal. Publication always needs exact-candidate human approval.",
            context,
        )
        answer = result.get("reply", "")
        if not isinstance(answer, str) or not answer.strip():
            raise PolicyError("The model returned an empty chat reply. Please retry.")
        answer = answer[:12000]
    except PolicyError as exc:
        error = str(exc)
    except Exception:
        error = "The chat request could not finish. Check the local service and retry."
    for secret in (config.llm_api_key, config.owner_token):
        if secret:
            answer, error = answer.replace(secret, "[redacted]"), error.replace(secret, "[redacted]")

    def finish(row, data):
        turn = next(t for t in data["chat"] if t["id"] == request_key)
        turn.update(
            reply=answer,
            error=error,
            status="failed" if error else "answered",
            usage=usage,
            model=selected.llm_model,
        )

    return store.mutate(run_id, finish)
