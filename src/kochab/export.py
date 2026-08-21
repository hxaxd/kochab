from __future__ import annotations

import json
from pathlib import Path

from kochab.session import open_session


def export_pack(host_dir: Path, out: Path, *, require_frozen: bool = False) -> Path:
    session = open_session(host_dir, require_frozen=require_frozen)
    surface = session.host.surface
    out.mkdir(parents=True, exist_ok=True)
    last = session.state.read_json("last-accepted.json") or {}
    accepted_version = surface.accepted()
    (out / "surface.diff").write_text(
        surface.diff(surface.baseline(), accepted_version) or "", encoding="utf-8"
    )
    (out / "journal.jsonl").write_bytes(
        session.state.journal_path.read_bytes()
        if session.state.journal_path.exists()
        else b""
    )
    before = last.get("eval_before")
    after = last.get("eval_after")
    if before:
        (out / "train-before.json").write_text(
            json.dumps(before, indent=2), encoding="utf-8"
        )
    if after:
        (out / "train-after.json").write_text(
            json.dumps(after, indent=2), encoding="utf-8"
        )
    gate = None
    if last.get("decision") == "accept":
        gate = {
            "passed": True,
            "score": last.get("gate_score"),
            "baseline_score": last.get("gate_baseline"),
        }
    (out / "gate.json").write_text(
        json.dumps(gate or {"passed": None, "note": "no accepted round yet"}, indent=2),
        encoding="utf-8",
    )
    (out / "argument.md").write_text(
        "# Evolution package\n\n"
        f"decision: {last.get('decision', 'none')}\n\n"
        f"## Summary\n\n{last.get('summary', '')}\n\n"
        f"## Argument\n\n{last.get('argument', '')}\n\n"
        f"## Refactor\n\n{last.get('refactor', '')}\n",
        encoding="utf-8",
    )
    (out / "evidence.json").write_text(
        json.dumps(
            {
                "categories": last.get("categories") or [],
                "refs": last.get("evidence_refs") or [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    meta = {
        "version": accepted_version,
        "baseline": surface.baseline(),
        "decision": last.get("decision"),
        "train": last.get("train"),
        "gate_score": last.get("gate_score"),
        "categories": last.get("categories") or [],
        "units": [u.id for u in surface.manifest().units],
    }
    (out / "pack.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out
