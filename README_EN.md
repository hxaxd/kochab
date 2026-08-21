<div align="center">

# Kochab

**Help Agents improve from evals, real traces, and human feedback.**

[![CI](https://img.shields.io/github/actions/workflow/status/hxaxd/kochab/ci.yml?style=for-the-badge&label=CI)](https://github.com/hxaxd/kochab/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge)](https://www.python.org/)
[![OTLP](https://img.shields.io/badge/Trace-OTLP-7C3AED?style=for-the-badge)](docs/interoperability.md)
[![License](https://img.shields.io/badge/License-MIT-059669?style=for-the-badge)](LICENSE)

[中文](README.md) · **English**

[Overview](#introduction) · [Capabilities](#capabilities) · [Quick start](#quick-start) · [Status](#status)

</div>

## Introduction

Deployed Agents keep meeting new failures, feedback, and edge cases.

Kochab turns that evidence into changes that are testable, reversible, and reviewable.

You declare what may change, how to evaluate it, and where traces come from.

Kochab handles diagnosis, editing, validation, refactoring, and acceptance in a Git copy.

> Original host files stay unchanged. The output is an evidence-backed evolution package.

## Capabilities

- 🧭 **Framework agnostic**: connect an Agent through three small boundaries.
- 🧪 **Eval driven**: combine cases, scores, feedback, outputs, and gold answers.
- 📡 **Production evidence**: read errors, automated scores, and human feedback from OTLP.
- 🔁 **Autonomous evolution**: let the model diagnose, edit, validate, and refactor.
- 🛡️ **Hidden gate**: run model-invisible holdout cases before acceptance.
- 🧬 **Reversible versions**: start from the accepted ref and restore it on failure.
- 📦 **Reviewable delivery**: export the diff, scores, evidence, and rationale.
- 🔌 **Standard integration**: support GenAI traces and common eval outputs.

## Support

| Area | Current support |
|---|---|
| Model API | OpenAI-compatible Chat Completions with tool calling |
| Tuning units | Declared prompts, skills, tool definitions, and workflow files |
| Agent traces | OTLP/HTTP · OTLP JSON/JSONL |
| Trace semantics | OpenTelemetry GenAI · OpenInference · Braintrust scores |
| Eval outputs | Native JSON · JSONL · Promptfoo · JUnit · Inspect |
| Runtime | Python 3.11+ · Git |

## Workflow

```text
Onboard
  Read-only discovery → Human review → Baseline eval → Frozen boundary

Evolve
  New evidence → Diagnose → Edit copy → Train eval → Generalize
                                              │
                                      Hidden holdout gate
                                         │         │
                                       Pass       Fail
                                         │         │
                                       Accept    Restore

Deliver
  Target diff + Before/after scores + Evidence refs + Rationale
```

## Quick start

### 1. Get Kochab

```bash
git clone https://github.com/hxaxd/kochab.git
cd kochab
python -m pip install -e ".[dev]"
python -m pytest -q
```

### 2. Configure a model

```bash
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://your-endpoint.example/v1"
export OPENAI_MODEL="your-tool-calling-model"
```

`OPENAI_BASE_URL` is optional when calling OpenAI directly.

### 3. Run the closed-loop example

```bash
kochab onboard examples/toy-desk --reset-state --freeze
kochab run examples/toy-desk
kochab gate examples/toy-desk
kochab export examples/toy-desk --out evolution-pack
```

The example moves from 0/10 to 10/10 train cases and passes 6 hidden cases.

### 4. Connect your Agent

```bash
kochab discover path/to/agent-host
kochab onboard path/to/agent-host --freeze
kochab daemon path/to/agent-host
```

Review `kochab-host.draft.yaml` before saving it as `kochab-host.yaml`.

See the [host integration guide](docs/host-binding.md) for the binding format.

## Good fits

- Prompts or workflows must keep adapting to new failures.
- The Agent, eval system, and observability stack are independent.
- Production feedback should become reviewable changes, not hot patches.
- The model may design improvements, but gates and rollback must stay deterministic.

## Security boundary

- The evolution model has no shell and no arbitrary host-file access.
- The model may edit only the tuning units declared in the binding.
- Holdout content, answers, and per-case results stay hidden from the model.
- Eval dependencies and case catalogs are sealed before evolution.
- OTLP input and host eval commands still belong inside a trusted deployment boundary.

Report security issues privately through the [security policy](SECURITY.md).

## Status

Kochab is an **experimental v0.1** project.

Onboarding, evolution, hidden gating, recovery, daemon mode, and export work end to end.

Dynamic tool synthesis, self-optimization, distributed execution, and hosting are not built.

See [implementation status](docs/implementation-status.md) for the exact boundary.

## Documentation

- [Host integration guide](docs/host-binding.md)
- [Interoperability](docs/interoperability.md)
- [Chinese design document](docs/design.zh-CN.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## License

[MIT License](LICENSE)
