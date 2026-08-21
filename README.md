<div align="center">

# Kochab

**让 Agent 从评测、真实轨迹与人类反馈中持续变好。**

[![CI](https://img.shields.io/github/actions/workflow/status/hxaxd/kochab/ci.yml?style=for-the-badge&label=CI)](https://github.com/hxaxd/kochab/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge)](https://www.python.org/)
[![OTLP](https://img.shields.io/badge/Trace-OTLP-7C3AED?style=for-the-badge)](docs/interoperability.md)
[![License](https://img.shields.io/badge/License-MIT-059669?style=for-the-badge)](LICENSE)

**中文** · [English](README_EN.md)

[项目介绍](#项目介绍) · [核心能力](#核心能力) · [工作路径](#工作路径) · [快速开始](#快速开始) · [项目状态](#项目状态)

</div>

## 项目介绍

Agent 上线以后，新的失败、反馈和边界问题会不断出现。

Kochab 把这些证据变成可验证、可回滚、可审阅的改进。

你只需声明三件事：它能改什么、如何评估、从哪里读取轨迹。

Kochab 在独立 Git 副本中完成诊断、修改、验证、重构和采纳。

> 原始宿主文件保持不变。最终交付物是一份带证据的进化包。

## 核心能力

- 🧭 **框架无关**：通过调优面、评测口和轨迹口连接现有 Agent。
- 🧪 **评测驱动**：把离线用例、评分、反馈和标准答案统一成证据。
- 📡 **真实反馈**：从 OTLP 轨迹中读取错误、自动评分和人类反馈。
- 🔁 **自主进化**：让模型完成诊断、修改、验证和泛化重构。
- 🛡️ **隐藏门禁**：采纳前运行模型不可见的 holdout 回归集。
- 🧬 **版本可逆**：每轮从已采纳版本开始，失败即恢复。
- 📦 **证据交付**：导出 diff、前后分数、证据引用和改进论证。
- 🔌 **标准接入**：兼容 OpenTelemetry GenAI、OpenInference 和常见评测输出。

## 支持范围

| 类别 | 当前支持 |
|---|---|
| 模型接口 | 支持工具调用的 OpenAI 兼容 Chat Completions |
| 调优对象 | 已声明的提示词、skills、工具定义和流程文件 |
| Agent 轨迹 | OTLP/HTTP · OTLP JSON/JSONL |
| 轨迹语义 | OpenTelemetry GenAI · OpenInference · Braintrust scores |
| 评测输出 | Native JSON · JSONL · Promptfoo · JUnit · Inspect |
| 运行环境 | Python 3.11+ · Git |

## 工作路径

```text
接入
  只读发现 → 人工确认 → 基线评测 → 冻结边界

进化
  新证据 → 诊断 → 修改副本 → 训练验证 → 泛化重构
                                      │
                               隐藏 holdout 门禁
                                  │         │
                                通过       失败
                                  │         │
                                采纳       回滚

交付
  目标 diff + 前后分数 + 证据引用 + 改进论证
```

## 快速开始

### 1. 取得项目

```bash
git clone https://github.com/hxaxd/kochab.git
cd kochab
python -m pip install -e ".[dev]"
python -m pytest -q
```

### 2. 配置模型

```bash
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://your-endpoint.example/v1"
export OPENAI_MODEL="your-tool-calling-model"
```

`OPENAI_BASE_URL` 在直接使用 OpenAI 时可以省略。

### 3. 跑通完整示例

```bash
kochab onboard examples/toy-desk --reset-state --freeze
kochab run examples/toy-desk
kochab gate examples/toy-desk
kochab export examples/toy-desk --out evolution-pack
```

示例会从 0/10 训练用例通过，进化到 10/10，并通过 6 个隐藏用例。

### 4. 接入自己的 Agent

```bash
kochab discover path/to/agent-host
kochab onboard path/to/agent-host --freeze
kochab daemon path/to/agent-host
```

先审阅发现阶段生成的 `kochab-host.draft.yaml`，再保存为 `kochab-host.yaml`。

绑定格式、占位符和评测输出要求见[宿主接入指南](docs/host-binding.md)。

## 适合的场景

- Agent 的提示词或流程会随新问题持续调整。
- 评测系统、观测系统与 Agent 框架彼此独立。
- 生产反馈需要沉淀成可审阅的改进，而不是直接热更新。
- 你希望模型设计优化过程，但必须保留门禁和回滚能力。

## 安全边界

- 进化模型没有 shell，也不能读取任意宿主文件。
- 模型只能修改绑定中明确声明的调优单元。
- holdout 内容、答案和逐用例结果不会暴露给模型。
- 评测依赖与用例目录在进化前冻结并校验。
- OTLP 输入和宿主评测命令仍应按可信边界部署。

安全问题请按[安全策略](SECURITY.md)私密报告。

## 项目状态

Kochab 当前是 **experimental v0.1**。

初始化、进化、隐藏门禁、失败恢复、持续模式和进化包已经跑通。

动态工具合成、自举优化、分布式执行和生产托管尚未实现。

完整边界见[实现状态与路线图](docs/implementation-status.md)。

## 参与项目

- [宿主接入指南](docs/host-binding.md)
- [互操作说明](docs/interoperability.md)
- [设计文档](docs/design.zh-CN.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## 常见问题

<details>
<summary><strong>Kochab 会直接修改生产 Agent 吗？</strong></summary>

不会。候选变更只发生在独立 Git 副本中，并以进化包交付。
</details>

<details>
<summary><strong>必须使用某个 Agent 框架吗？</strong></summary>

不需要。宿主只需提供可声明的文件、评测命令和 OTLP 轨迹。
</details>

<details>
<summary><strong>Kochab 是固定算法的提示词优化器吗？</strong></summary>

不是。模型设计每轮改进，框架负责冻结边界、验证、门禁和回滚。
</details>

## License

[MIT License](LICENSE)
