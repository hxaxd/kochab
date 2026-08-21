# Host integration

A host binding tells Kochab what it may change, how to evaluate a candidate, and where
to read Agent traces.

## Binding file

Save the reviewed binding as `kochab-host.yaml` in the host root.

```yaml
surface:
  units:
    - id: system
      category: knowledge
      path: surface/SYSTEM.md
      format: markdown
      max_bytes: 20000

eval:
  command: ["{python}", "eval/run.py"]
  list_args: ["--list"]
  run_args: ["--surface-dir", "{surface_dir}", "--cases", "{case_ids}"]
  criteria_path: eval/CRITERIA.md
  cases_path: eval/cases.json
  dependency_paths: [eval/run.py]
  format: kochab
  pass_threshold: 1.0
  timeout_seconds: 120

trace:
  kind: otlp-json
  path: traces/otel.jsonl

gate:
  holdout_ids: [hidden-1, hidden-2]
```

## Tuning surface

Each unit is a UTF-8 text file under the host root.

`category` is one of `knowledge`, `experience`, `tool`, or `process`.

Kochab copies these units into an isolated Git repository before editing them.

## Evaluation command

Commands are argument arrays. They are never passed through a shell.

Available placeholders:

| Placeholder | Value |
|---|---|
| `{python}` | Active Python interpreter |
| `{surface_dir}` | Isolated materialization of the requested candidate |
| `{case_ids}` | Comma-separated selected case ids |
| `{result_path}` | Exact result file inside the materialized candidate |
| `{result_dir}` | Directory for frameworks that choose a result filename |

Without `result_path` or `result_glob`, Kochab parses evaluator stdout.

`dependency_paths` should cover local evaluators, rubrics, datasets, and helper modules.

## Case catalog

`list_args` must produce a JSON array or an object with a `cases` array.

```json
[
  {
    "id": "case-1",
    "label": "short label",
    "question": "model-visible prompt",
    "gold": "optional model-visible train answer"
  }
]
```

Holdout ids remain in the host catalog but are filtered from every model-visible tool.

## Traces

`kochab daemon` listens on `127.0.0.1:4318/v1/traces` by default.

Send OTLP directly or use an OpenTelemetry Collector to fan out existing traffic.

See [interoperability](interoperability.md) for supported semantics and eval formats.

## Freeze and evolve

```bash
kochab onboard path/to/host --freeze
kochab run path/to/host
kochab daemon path/to/host
```

Onboarding seals the binding, source units, evaluator dependencies, rubric, and cases.

Use `--reset-state` only when source tuning units intentionally change.
