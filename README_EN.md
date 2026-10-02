# Kochab · 紫微

**Turn real requirements into a continuous cycle of capability development.**

[中文](README.md) · English

Kochab is a teaching repository with two layers: an explanation of how capabilities develop, and minimal interfaces for benchmarks, agent evolution and data feedback, with a skill for building a benchmark.

Real requirements → benchmark → evaluation and improvement → real usage → regression tasks and training data → the next cycle.

## Layer one: explanation

[How agents extend the capability boundary of language models](docs/reference/capability-cycle.md) (Chinese)

The text connects model training with tasks, environments, tools and verifiers, then rubric calibration, agent improvement and data feedback. The [PDF](docs/reference/capability-cycle.pdf) and text are revised together, preserving the original account of capability development and training feedback.

## Layer two: interfaces and skill

The [interface guide](docs/interfaces.md) connects the explanation to the code.

| Part | Entry |
| --- | --- |
| Benchmark: problems, environment, tools and verifiers | [benchmark.py](src/kochab/benchmark.py) · [Shared records](src/kochab/records.py) |
| Task synthesis: challenge generation, validation and feedback | [task_synthesis.py](src/kochab/task_synthesis.py) · [Example generation prompt](examples/paper_summary/prompts/task-synthesis.md) |
| Agent evolution: proposals, re-evaluation and selection | [agent_evolution.py](src/kochab/agent_evolution.py) · [Example revision prompt](examples/paper_summary/prompts/agent-revise.md) |
| Rubric calibration: repeated judgments, disagreement, revision and human review | [rubric.py](src/kochab/rubric.py) · [Example draft prompt](examples/paper_summary/prompts/rubric-draft.md) · [Example revision prompt](examples/paper_summary/prompts/rubric-revise.md) |
| Data feedback: regression tasks and trajectory preparation | [data_feedback.py](src/kochab/data_feedback.py) |
| Build a benchmark from a real requirement | [SKILL.md](SKILL.md) |
| Standalone example: paper summarization | [Example guide](examples/paper_summary/README.md) |

Give your coding agent this repository's `SKILL.md`, your requirement and the existing project. The skill helps define the task boundary, build the problems, environment, tools and verifiers, and check reproducibility and execution.

The core provides domain-independent records and interfaces, with no default benchmark. A separate paper-summary example implements an environment, tools, evaluation and three independent experiments: task synthesis, agent prompt evolution and rubric calibration. Papers and a model adapter are supplied explicitly. Each experiment has a round limit and retains its evidence; rubric candidates await human review. A human-directed data-feedback example extracts replayable regression tasks and selected training turns. The Python package requires Python 3.10+ and has no runtime dependencies. The guide, skill and prompts are in Chinese.

```sh
python -m pip install -e .
```

[MIT](LICENSE) © 2026 hxaxd
