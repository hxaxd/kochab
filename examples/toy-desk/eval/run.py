from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent import answer

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((Path(__file__).with_name("cases.json")).read_text(encoding="utf-8"))
CASES_BY_ID = {row["id"]: row for row in CASES}


def list_cases() -> list[dict]:
    return [
        {
            "id": row["id"],
            "label": row.get("label", row["id"]),
            "question": row["question"],
            "gold": row.get("gold"),
        }
        for row in CASES
    ]


def score_case(system: str, row: dict) -> dict:
    output = answer(system, row["question"])
    missing = [needle for needle in row["must_include"] if needle.lower() not in output.lower()]
    ok = not missing
    feedback = (
        "all required policy details present"
        if ok
        else "missing required policy detail: " + ", ".join(missing)
    )
    return {
        "id": row["id"],
        "score": 1.0 if ok else 0.0,
        "feedback": feedback,
        "output": output,
    }


def run_cases(surface_dir: Path, case_ids: list[str]) -> dict:
    system_path = surface_dir / "surface" / "SYSTEM.md"
    system = system_path.read_text(encoding="utf-8")
    results = []
    visibility = os.environ.get("KOCHAB_EVAL_VISIBILITY", "train")
    traces_path = ROOT / "traces" / "otel.jsonl"
    if visibility == "train":
        traces_path.parent.mkdir(parents=True, exist_ok=True)
    fh = traces_path.open("a", encoding="utf-8") if visibility == "train" else None
    try:
        for case_id in case_ids:
            row = CASES_BY_ID[case_id]
            scored = score_case(system, row)
            results.append(scored)
            if fh:
                trace_id = uuid.uuid4().hex
                span_id = uuid.uuid4().hex[:16]
                started = time.time_ns()
                ended = time.time_ns()
                request = {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {"key": "service.name", "value": {"stringValue": "toy-desk"}},
                                    {"key": "kochab.eval.visibility", "value": {"stringValue": visibility}},
                                ]
                            },
                            "scopeSpans": [
                                {
                                    "scope": {"name": "toy-desk.agent", "version": "1"},
                                    "spans": [
                                        {
                                            "traceId": trace_id,
                                            "spanId": span_id,
                                            "name": "invoke_agent desk",
                                            "kind": "SPAN_KIND_INTERNAL",
                                            "startTimeUnixNano": str(started),
                                            "endTimeUnixNano": str(ended),
                                            "status": {"code": "STATUS_CODE_OK"},
                                            "attributes": [
                                                {"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}},
                                                {"key": "gen_ai.agent.name", "value": {"stringValue": "desk"}},
                                                {"key": "openinference.span.kind", "value": {"stringValue": "AGENT"}},
                                                {
                                                    "key": "gen_ai.input.messages",
                                                    "value": {"stringValue": json.dumps([{"role": "user", "parts": [{"type": "text", "content": row["question"]}]}])},
                                                },
                                                {
                                                    "key": "gen_ai.output.messages",
                                                    "value": {"stringValue": json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": scored["output"]}]}])},
                                                },
                                            ],
                                            "events": [
                                                {
                                                    "name": "gen_ai.evaluation.result",
                                                    "timeUnixNano": str(ended),
                                                    "attributes": [
                                                        {"key": "gen_ai.evaluation.name", "value": {"stringValue": "policy_correctness"}},
                                                        {"key": "gen_ai.evaluation.score", "value": {"doubleValue": scored["score"]}},
                                                        {"key": "gen_ai.evaluation.explanation", "value": {"stringValue": scored["feedback"]}},
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
                fh.write(json.dumps(request) + "\n")
    finally:
        if fh:
            fh.close()
    mean = sum(r["score"] for r in results) / len(results) if results else 0.0
    return {"score": mean, "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--surface-dir")
    parser.add_argument("--cases", default="")
    args = parser.parse_args()
    if args.list:
        json.dump(list_cases(), sys.stdout)
        sys.stdout.write("\n")
        return
    if not args.surface_dir:
        parser.error("--surface-dir is required")
    ids = [part for part in args.cases.split(",") if part]
    if not ids:
        ids = [row["id"] for row in CASES]
    json.dump(run_cases(Path(args.surface_dir), ids), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
