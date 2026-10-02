# 紫微 · Kochab

**从真实需求出发，理解并构建模型能力持续改进的闭环。**

中文 · [English](README_EN.md)

Kochab 是一个两层教学仓库：第一层讲清能力如何形成，第二层用尽可能少的接口表达 Benchmark、Agent 自进化与数据回流，并提供构建 Benchmark 的 skill。

真实需求 → Benchmark → 评测与改进 → 真实使用 → 失败回归与训练数据 → 下一轮能力建设。

## 第一层：讲解

[智能体如何扩展大语言模型的能力边界](docs/reference/capability-cycle.md)

从模型训练讲到任务、环境、工具和验证器，再连接 Rubric 校准、Agent 改进与数据回流。[PDF](docs/reference/capability-cycle.pdf) 与正文同步修订，保留原有能力形成与训练回流的主线。

## 第二层：接口与 skill

[接口说明](docs/interfaces.md) 连接讲解与代码。

| 部分 | 入口 |
| --- | --- |
| Benchmark：问题、环境、工具、验证器 | [benchmark.py](src/kochab/benchmark.py) · [共享记录](src/kochab/records.py) |
| 任务合成：生成挑战、审核、反馈 | [task_synthesis.py](src/kochab/task_synthesis.py) · [示例出题提示词](examples/paper_summary/prompts/task-synthesis.md) |
| Agent 自进化：提案、复测、选择 | [agent_evolution.py](src/kochab/agent_evolution.py) · [示例修改提示词](examples/paper_summary/prompts/agent-revise.md) |
| Rubric 校准：重复判断、不一致、修订、抽检 | [rubric.py](src/kochab/rubric.py) · [示例初稿提示词](examples/paper_summary/prompts/rubric-draft.md) · [示例修订提示词](examples/paper_summary/prompts/rubric-revise.md) |
| 数据回流：回归任务、轨迹清洗 | [data_feedback.py](src/kochab/data_feedback.py) |
| 从真实需求构建 Benchmark | [SKILL.md](SKILL.md) |
| 独立示例：论文总结 | [示例说明](examples/paper_summary/README.md) |

把本仓库的 `SKILL.md` 交给你的编程智能体，同时提供真实需求和现有项目。Skill 会帮助明确任务边界，构建问题、环境、工具与验证器，并核对能否复现和执行。

核心保持领域无关的记录与接口，不创建默认 Benchmark。论文总结示例实现环境、工具、评测，以及三个独立实验：任务合成、Agent 提示词自进化、Rubric 校准。运行时显式传入论文与模型适配函数，每种实验都有轮数上限并保存证据；Rubric 候选留待人类抽检。数据回流示例按人类反馈提取回归任务和训练样本。Python 包需要 3.10+，无运行时依赖。

```sh
python -m pip install -e .
```

[MIT](LICENSE) © 2026 hxaxd
