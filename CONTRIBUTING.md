# Contributing

Kochab is an experimental project. Small, test-backed changes that preserve the
three-contract boundary are welcome.

## Development setup

```bash
git clone https://github.com/hxaxd/kochab.git
cd kochab
python -m pip install -e ".[dev]"
python -m pytest -q
```

## Before opening a pull request

- Keep framework-specific behavior in adapters, not the core loop.
- Add focused tests for new trace semantics, result formats, or acceptance rules.
- Preserve hidden-gate isolation: model-visible tools must not reveal holdout ids,
  prompts, gold answers, per-case results, or traces.
- Never commit provider credentials, production traces, `.kochab` state, or exported
  data containing private model inputs and outputs.
- Update `docs/implementation-status.md` when a roadmap item becomes real.

Run the complete suite before submitting:

```bash
python -m pytest -q
python -m compileall -q src tests examples
```

For substantial contract or lifecycle changes, open an issue first so the intended
boundary is explicit.
