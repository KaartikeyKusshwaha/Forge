"""Bound model evidence without silently cutting source files or candidate edits."""

import json


def check_evidence(check):
    output = check.get("output", "")
    if "\nTESTS\n" in output:
        output = output.rsplit("\nTESTS\n", 1)[1]
    return {
        **{
            k: check[k] for k in ("phase", "command", "exit_code", "status", "count", "run_url") if k in check
        },
        "output": output[-4000:],
    }


def compact_evidence(context):
    """One smaller retry for provider capacity limits; immutable source stays intact."""

    def walk(value, key=""):
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, dict):
            if {"exit_code", "count"} <= value.keys():
                return check_evidence(value)
            return {k: walk(v, k) for k, v in value.items() if k not in {"file_modes", "environment_plan"}}
        if isinstance(value, str) and key in {"output", "error"}:
            return value[-2000:]
        return value

    result = walk(context)
    return result if len(json.dumps(result)) < len(json.dumps(context)) else None
