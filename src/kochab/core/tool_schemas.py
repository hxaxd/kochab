from __future__ import annotations

from typing import Any


def evolve_tool_schemas() -> list[dict[str, Any]]:
    return [
        _fn("surface_manifest", "List tunable units and the current work-copy version."),
        _fn("surface_read", "Read one tunable unit.", {"unit_id": _str("Unit id from the manifest.")}, ["unit_id"]),
        _fn(
            "surface_apply", "Replace one unit's full contents. Returns the new version.",
            {"unit_id": _str("Unit id."), "content": _str("Full new file contents.")},
            ["unit_id", "content"],
        ),
        _fn(
            "surface_diff", "Diff two work-copy versions. Use BASE for round start and HEAD for current.",
            {"a": _str("Version or BASE/HEAD."), "b": _str("Version or BASE/HEAD.")}, ["a", "b"],
        ),
        _fn("surface_rollback", "Hard-reset the work copy to a version.", {"to": _str("Version or BASE.")}, ["to"]),
        _fn("eval_suites", "List train cases only."),
        _fn("eval_criteria", "Read the host evaluation criteria."),
        _fn(
            "eval_gold", "Gold answer for a train case, if the host has one.",
            {"case_id": _str("Train case id.")}, ["case_id"],
        ),
        _fn(
            "eval_run", "Run train cases against a work-copy version. Empty case_ids means all train cases.",
            {
                "case_ids": {"type": "array", "items": {"type": "string"}, "description": "Train ids, or empty for all."},
                "version": _str("Version or HEAD. Defaults to HEAD."),
            },
        ),
        _fn(
            "trace_query", "List recent OpenTelemetry traces. Quality failures are feedback, not span errors.",
            {
                "status": _str("Optional runtime status, e.g. error."),
                "feedback_name": _str("Optional evaluation or annotation name."),
                "max_feedback_score": {"type": "number"},
                "has_human_feedback": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
        ),
        _fn("trace_read", "Read one trace by ref.", {"ref": _str("Trace ref.")}, ["ref"]),
        _fn("notes_read", "Read your working notes."),
        _fn("notes_write", "Overwrite your working notes.", {"content": _str("Markdown notes.")}, ["content"]),
        _fn("journal_read", "Read recent evolution journal entries."),
        _fn(
            "finish_round",
            "End the round. accept runs the hidden gate; failure continues. reject restores round start.",
            {
                "decision": {"type": "string", "enum": ["accept", "reject"]},
                "summary": _str("One-paragraph summary."),
                "argument": _str("Why these changes, tied to evidence."),
                "categories": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["knowledge", "experience", "tool", "process"]},
                },
                "evidence_refs": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Train case ids or trace refs inspected in this round.",
                },
                "refactor": _str("How the green solution was generalized or simplified."),
            },
            ["decision", "summary", "argument", "categories", "evidence_refs", "refactor"],
        ),
    ]


def _str(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _fn(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object", "properties": properties or {}, "required": required or [],
            },
        },
    }
