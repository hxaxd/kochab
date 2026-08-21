# Implementation status

Kochab is an experimental v0.1 prototype. This page separates working code from
architectural intent so the design document is not mistaken for a feature list.

## Implemented

| Area | Current implementation | Evidence |
|---|---|---|
| Tuning surface | Declared files, isolated Git work copy, baseline/accepted refs, diff and rollback | `test_surface.py`, `test_run_round.py` |
| Evaluation | Shell-free command runner; native JSON/JSONL, Promptfoo, JUnit and Inspect parsers | `test_eval_cli.py`, `test_eval_formats.py` |
| Traces | OTLP/HTTP JSON, gzip JSON and protobuf; OTLP JSON/JSONL files; GenAI, OpenInference and Braintrust projection | `test_otel.py`, `test_otlp_receiver.py` |
| Discovery | Read-only repository tools and validated `kochab-host.yaml` draft | `test_discovery.py` |
| Onboarding | Exercises all three ports, captures train/holdout baselines and seals local dependencies | `test_onboarding.py` |
| Evolution | Tool-calling loop, red/green/refactor evidence, complete-train requirement and hidden holdout gate | `test_run_round.py` |
| Recovery | Accepted-version restoration and rollback of gate/state files on failed acceptance | `test_run_round.py` |
| Continuous mode | OTLP receiver, persistent polling cursor and evidence-triggered rounds | `test_lifecycle.py` |
| Delivery | Accepted-version diff, argument, evidence and before/after scores | `test_lifecycle.py` |

## Partial by design

- `TracePort.subscribe()` is a snapshot iterator. Continuous mode currently polls a
  file-backed trace port with a persistent cursor.
- External evaluation libraries are supported through their CLI/JUnit/native export,
  not by embedding every framework runtime.
- Non-OTLP trace stores need a host-side converter that emits OTLP.
- Kochab can edit declared tool files but cannot add new manifest entries at runtime.
- Context compression has a hook but no bundled compression policy.

## Not implemented

- Dynamic tool synthesis or `add_tool`.
- GEPA, ACE, or other optimizer plugins.
- Self-tuning Kochab with Kochab.
- Distributed workers, hosted control plane, production deployment, or multi-tenant
  isolation.
- A production-host reference integration. `examples/toy-desk` is deterministic and
  intentionally small.

These are roadmap items, not compatibility promises.
