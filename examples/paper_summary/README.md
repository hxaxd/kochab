# 论文总结：一个独立示例

核心提供记录、接口和四个可复用循环；示例接入具体环境、模型调用与选择策略，不要求继承。先读 `benchmark.py`，再按需要看任务合成、Agent 改进、Rubric 校准和数据回流。

## 文件与职责

| 文件 | 做什么 |
| --- | --- |
| [benchmark.py](benchmark.py) | `build_benchmark` 组装四部分；`PaperBenchmarkRunner` 装配通用运行器，`PaperAgentFactory` 解析配置并记录模型事件 |
| [environment.py](environment.py) | `PaperEnvironment` 固定论文；`PaperSession` 提供逐页阅读、搜索与状态记录 |
| [agent.py](agent.py) | `PaperAgent` 使用工具，提交总结和引文；模型函数由外部注入 |
| [verifiers.py](verifiers.py) | `FormatVerifier` 检查格式、长度和引文；`RubricVerifier` 判断语义质量 |
| [rubric.md](rubric.md) | 人工写出的初始评分标准，尚未校准 |
| [task_synthesis.py](task_synthesis.py) | `PaperTaskSynthesizer` 出题，`PaperTaskValidator` 审核，循环将实测反馈交给下一轮 |
| [agent_evolution.py](agent_evolution.py) | `PaperPromptOptimizer` 归因、修改提示词、比较复测结果 |
| [rubric_calibration.py](rubric_calibration.py) | `PaperRubricAssessor` 复评，`PaperRubricOptimizer` 修订，`PaperRubricSelector` 选择候选 |
| [prompts/](prompts/) | 本例的出题、Agent 修改与 Rubric 生成模板，由上述三个实验读取 |
| [data_feedback.py](data_feedback.py) | `PaperDataCurator` 按人类反馈提取回归任务、整理训练步骤；提供离线导出入口 |
| [artifacts.py](artifacts.py) | `ArtifactStore` 按内容哈希保存快照；报告中的材料直接是 JSON 值 |
| [run.py](run.py) | 读取命令行参数，选择一个实验，保存报告 |

这些模板规定本例的生成任务和输出约束；迁移到其他领域时，应按自己的任务、证据和调用协议调整。

## 环境与验证

每篇论文对应一个任务，输入包含阅读目的和正文长度要求。PDF 首次提取后固定为文本快照；UTF-8 文本按换页符（U+000C）分页面。每次 reset 都创建新会话，使用固定内容和 seed。`read_page` 读取原文，`search` 返回命中片段；模型输入输出、观察、工具结果和终止原因都进入轨迹。

确定性检查覆盖输出结构、正文的非空白字符数、页码及引文是否存在。Rubric 分别评价忠实性、需求覆盖、证据支持和清晰度，取 0–4 分。格式失败不评分，Judge 异常单独记录；不把两类结果混成总分。引文存在不等于它支持结论。

本例是文本环境，PDF 提取需要核对，空白页面会被拒绝；图表、公式和扫描件需要额外解析。环境可重放不代表远程模型输出相同。

## 运行与改进

从仓库根目录执行，提供自己的论文和模型函数：

```sh
python -m pip install -e .
python -m pip install pypdf  # 仅 PDF 输入需要
python -m examples.paper_summary.run paper-a.pdf paper-b.pdf \
  --goal "理解主要贡献、实验依据和适用限制" \
  --model my_backend:complete --model-id "实际模型版本与采样配置" \
  --out evaluation.json
```

`complete(prompt: str) -> str` 由使用者提供，负责 API、凭证和超时，返回原始模型文本。CLI 复用同一函数；程序化调用可为不同角色注入不同模型。报告保存评测结果及全部引用材料，运行前要求输出文件不存在。

以下三种实验互斥，每次只改变一个对象：

| 附加参数 | 流程 | 报告字段 |
| --- | --- | --- |
| `--synthesize 2 --synthesis-rounds 3` | 每轮最多出两题，审核入集后复测，最多三轮 | `synthesis_rounds` |
| `--evolve 3` | 最多三轮提示词修改、固定条件复测、选择 | `evolution_rounds` |
| `--calibrate-rubric 3 --judge-repeats 3` | 初稿及最多三个修订版，对固定轨迹各评分三次 | `rubric_calibration` |

**任务合成**保持论文、工具、seed、篇幅约束和评分标准不变，只生成新的阅读目的。参考解先过脚本检查，再由独立模型调用审核可完成性、证据支持和重复情况。参考解不交给答题 Agent。通过审核的任务进入新版本，旧任务保留；是否更难需看实际执行，不能跨版本直接比较平均分。

**Agent 改进**只修改提示词。既有有效输出不能变为无效，既有评分的各维度不能下降；同时须有一个维度上升，或某个原本无效的任务变得有效且四项均不低于 3。评分异常、退化或没有改善都拒绝。接纳后继续，拒绝、提示词未变、出错或达到预算时停止。所有候选和理由留档。这是开发集单次选择规则，实际效果需要重复运行和独立论文验证。

**Rubric 校准**根据需求生成初稿，在同一份轨迹上独立复评，最多四个调用并行；任一维度极差至少 2 分就标记分歧，再由另一轮模型调用总结修订。候选的分歧案例数增加便拒绝；无分歧、候选未变、拒绝或达到预算时结束，调用错误或无可评分证据会单独报告。正常结束仍是 `pending_human_review`；`review_samples` 包含最后采纳版本的全部案例，`human_review` 留空，既抽检分歧，也抽检未标记项。适配函数需要支持并发调用；采样配置应能观察判断差异。

重复评分只是 CLI 选用的一种策略。程序化调用 `PaperRubricOptimizer.revise(rubric, cases)` 时，`cases` 可以提供轨迹对、专家原话、偏好、没有答案的争议，或多版 Rubric。通用 `evolve_rubric` 通过注入复评器和选择器完成迭代，见[接口说明](../../docs/interfaces.md#rubric-自进化)。

人工检查后可将候选文本保存为文件，通过 `--agent-prompt prompt.md` 或 `--rubric reviewed-rubric.md` 用于下一次运行。指定 Rubric 时校准从该版本开始，否则生成初稿。候选提示词见最终 `evaluation.agent` 引用的配置，候选 Rubric 见 `rubric_calibration.candidate_rubric`。更换评分标准需要重建对照。

## 数据回流

先阅读报告，按其中的任务 ID 写一份 `reviews.json`。记录审核人、判断理由、是否回归，以及允许训练的模型调用序号（从 0 开始）；没有选中的步骤不会导出：

```json
{
  "报告里的任务ID": {
    "reviewer": "审核人",
    "notes": "说明失败为何值得回归、选中步骤为何适合学习，并确认内容可以用于训练",
    "regression": true,
    "training_steps": [1]
  }
}
```

```sh
python -m examples.paper_summary.data_feedback evaluation.json reviews.json --out feedback.json
```

回归出口先重置原环境、回放工具动作并核对返回结果，证据不足不输出任务。训练出口只保留人类选中的完整输入与响应，检查格式、去重，输出 `messages` 样本；输入保留此前可见的工具结果。最终失败的轨迹也可以选择其中有价值的步骤，不能自动把高分等同于整条轨迹都值得训练。材料去敏和语义质量由审核者判断。

`feedback.json` 包含 `regression_tasks`、`training_samples`、处理理由及来源材料。下一次运行增加 `--regressions feedback.json`，即在当前开发集导入回归任务、按问题与初始条件去重，再重新评测；环境和工具版本必须一致。封存测试不进入这条回路。这里演示数据出口，不执行模型训练。

## 验证边界

`python -m unittest discover -s tests -v` 验证环境重放、基线评测、任务合成、Agent 改进、Rubric 校准、数据导出与回归再评测。模型回复是明确标记的离线替身；测试验证流程，真实效果仍需接入模型并人工抽检。
