# 从讲解到接口

`src/kochab` 分成三部分：描述事实的数据结构、接入具体系统的接口，以及组织这些接口的核心循环。`Protocol` 规定必须实现的方法，不要求继承；循环可以直接调用。核心没有默认任务、模型服务或评分算法，[论文总结示例](../examples/paper_summary/README.md) 提供一套具体实现。

| 核心流程 | 入口 | 接入方提供什么 |
| --- | --- | --- |
| Benchmark 运行 | `run_benchmark` | 材料仓库、Agent 工厂、任务、环境、工具和验证器 |
| Agent 自进化 | `evolve_agent` | 运行器，以及 `propose` / `decide` 策略 |
| 任务合成 | `synthesize_tasks` | 运行器、出题者、审核者和入集编辑器 |
| Rubric 自进化 | `evolve_rubric` | 修订材料、优化器、复评器和选择器 |

四个流程分别位于 [benchmark.py](../src/kochab/benchmark.py)、[agent_evolution.py](../src/kochab/agent_evolution.py)、[task_synthesis.py](../src/kochab/task_synthesis.py) 和 [rubric.py](../src/kochab/rubric.py)。Agent 和 Rubric 改进都遵循“提案、复评、选择”，但前者重新执行任务，后者在固定材料上检验判断标准，因此各自保留直接可读的循环。

## 共用记录

[records.py](../src/kochab/records.py) 定义 `Task`、`Trace`、`Judgment`、`CaseResult` 和 `Evaluation`。一条轨迹保留任务、执行者版本、事件、结果与环境终态；一次评测保留逐题轨迹及所有判断，不只保存平均分。

`Artifact.ref` 指向不可变内容或固定版本。`ArtifactStore.put` 保存快照，`get` 解析引用；调用者不能原地改写已保存内容。仓库可以使用文件、数据库或服务，不要求材料都是文本。`Judgment.value` 也不限定为分数，可以是布尔值、向量、标签或结构化回答。

三个改进循环都有逐轮记录和 `stop_reason`。记录区分提案、复评、选择和异常；被拒绝的候选仍保留。返回的当前版本是最后采纳的版本，预算耗尽不表示改进成功。初始参数错误直接报错，运行中的失败写进记录。调用超时、取消和单次模型预算由接入方控制；核心限制改进轮数和每轮出题数量，不实现后台调度。

## Benchmark

一个 Benchmark 包含任务、环境、工具和验证器。任务可以是一段描述，也可以是交互协议或另一个系统。

| 接口 | 必须提供的方法与责任 |
| --- | --- |
| `Environment` | `reset(initial_state, seed=...)`：建立独立会话 |
| `Session` | `observe`、`call`、`snapshot`、`close`：观察、行动、快照和释放资源 |
| `Agent` | `run(problem, tools, session)`：执行任务并返回产物引用 |
| `AgentFactory` | `create(definition, record)`：从固定配置创建 Agent，记录其内部事件 |
| `Verifier` | `definition` 与 `verify(trace)`：标识版本并根据证据作出判断 |
| `BenchmarkRunner` | `run(agent, benchmark)`：返回完整评测；可以包装核心运行函数 |

`run_benchmark` 每题重置环境，通过包装 Session 记录观察和工具调用。Agent 工厂通过 `record` 补充模型输入输出、上下文处理等内部事件，不要求环境对象提供额外的 `events` 属性。每题结束前尝试快照，并始终尝试关闭已经建立的会话。初始化、执行、快照和关闭错误留在事件里；无法取得终态时，`Trace.final_state` 为 `None`。验证器分别消费同一轨迹，一个验证器出错不会丢掉其他判断。

`Benchmark.definition` 指向固定清单，记录任务划分、环境、工具、验证器、执行预算和指标规则。修改这些条件就产生新版本。运行器的评测结果必须对应完整任务与验证器清单；Agent 改进和多轮任务合成都会核对版本与完整性。

相同环境版本、初始状态、seed 和动作序列应重现相同状态变化，实时依赖需要冻结或回放。模型输出的随机性另行记录和评估。隐藏答案不能通过问题、观察或工具泄露给执行者。开发任务可以参与迭代，封存测试不能进入出题和修改上下文；具体数据划分由接入方检查，核心不解析领域清单格式。

## Agent 自进化

`AgentEvolution.propose(baseline)` 根据已有评测提出 `AgentProposal`，包含候选版本、修改理由和证据。`decide(baseline, trial)` 根据同条件复测返回 `SelectionDecision`。修改者可以是人类、模型或外部 Agent，修改对象可以是提示词、Context、工具使用方式或工作流；核心不规定搜索算法。

`evolve_agent` 固定 Benchmark，以最近一次采纳的结果提出下一版，复测后才决定是否替换。拒绝、候选未变、异常或达到轮数上限时结束。复测版本不符、缺题或缺验证器时，不会进入选择步骤。

论文示例只改变答题提示词，用[示例修订提示词](../examples/paper_summary/prompts/agent-revise.md)分析失败。选择规则逐题检查退化，要求出现实际改善；模型、任务、预算和验证器保持不变。这是一个开发集策略，独立验证仍需使用未参与修改的任务。若问题出在环境或评分标准，应另行修复并重建基线。

## 任务合成

`TaskSynthesizer.propose(benchmark, feedback, count=...)` 提出 `TaskProposal`，保留来源任务、出题理由、私有参考解或验证证据。`TaskValidator.validate(proposal, benchmark)` 检查候选是否相关、可复现和可验证，返回 `TaskReview`。

`BenchmarkEditor.admit(benchmark, proposal, review)` 保存入集依据并生成新清单。`expand_benchmark` 负责逐题审核和入集，后一个候选可以看见本批已经接纳的题目，因此能发现批内重复。核心要求新版本只追加该题，保留原有题目、环境、工具和验证器；领域编辑器负责具体存储方式。

`synthesize_tasks` 在新题集上运行固定 Agent，把实际结果交给下一轮出题者。没有新题、出现流程错误或用尽预算时停止。复测失败时，新清单仍保留在轮次记录中，返回的 Benchmark 与评测则保持为上一对完整结果。审核通过说明任务可用，不能代替实测来证明它更难。

论文示例保持论文、工具、篇幅和评分标准不变，合成新的阅读目的；参考解先过脚本验证，再由独立模型调用审核。私有参考解只用于审核，不放入执行者的任务或可见环境。

## Rubric 自进化

Rubric 定义评分维度、证据要求和判断边界。修改它的依据不只有重复评分分歧：两条轨迹的比较、专家解释、只有优劣顺序的偏好、没有答案的争议，甚至几版标准之间的比较，都可以成为输入。

`RubricCase` 表达一组相关材料。`traces`、`judgments`、`rubrics`、`feedback` 都是可选的元组，`instruction` 说明这组材料在讨论什么。`feedback` 引用的内容不限制格式；偏好针对哪条轨迹、专家意见来自谁等关系，可在反馈内容或说明中表达。

```python
from kochab.rubric import RubricCase

# 两条轨迹及专家的原话；无需先转换成分数。
expert_case = RubricCase(
    traces=(trace_a, trace_b),
    feedback=(store.put("第一条说明了适用边界，第二条把局部结论说成了普遍结论。"),),
)

# 只有偏好也可以；这里明确用 traces 中的下标指认对象。
preference_case = RubricCase(
    traces=(trace_a, trace_b), feedback=(store.put({"preferred": 0}),),
)

# 只有争议，没有标准答案：后续需要调查，不替使用者预设谁对谁错。
disputed_case = RubricCase(
    traces=(trace_a, trace_b), instruction="这两条轨迹有争议，检查现有标准漏掉了什么。",
)

# 不提供轨迹，也能比较几版标准的要求和边界。
comparison_case = RubricCase(
    rubrics=(rubric_a, rubric_b), instruction="比较这两版标准的证据要求。",
)
```

`RubricOptimizer.draft(requirement)` 用于冷启动；`revise(rubric, cases)` 根据材料返回完整新版和修改摘要。只想得到一份修订稿时，可以直接调用 `revise`。没有专家答案不妨碍提出修改，但材料不足的地方应说明不确定性，不编造专家结论。论文示例的[修订提示词](../examples/paper_summary/prompts/rubric-revise.md)遵循这一约定。

需要迭代时，调用 `evolve_rubric`，再接入两个接口：`RubricAssessor.assess(rubric, cases)` 检查标准，返回发现、证据和当前状态；`RubricSelector.decide(baseline, trial)` 比较前后检查，决定是否采用。复评可以调查争议、检查是否解释专家偏好、比较不同标准，也可以重复调用 Judge；不要求一律计算某个分数。

循环先检查当前标准，再提出修订、复评和选择。原始案例每轮保留，新调查只作为补充。`complete` 表示复评策略决定不再修改，`insufficient_evidence` 表示材料不足，`error` 表示检查失败；后两种情况不采用候选。即便所有判断变得一致，也不自动说明 Rubric 正确。

`RubricEvaluator.repeat`、`JudgmentBatch` 和 `JudgmentConsistency.check` 保留为重复判断策略的接口。`disagreement_case` 将这类分歧转换成普通 `RubricCase`，并非所有修订都必须经过它。`HumanReview` 可记录真实的人类抽检意见，通用循环不会替人类填写结论，也不强制每种接入都必须有人工步骤。

论文 CLI 采用重复评判这一个教学策略：固定轨迹，任一评分维度的极差至少 2 分便标记分歧，修订后复评；候选的分歧案例数增加就拒绝。错误或无可评分证据单独报告。报告保留全部检查和采纳决定，抽检材料指向最后采纳的版本；正常结束仍为 `pending_human_review`，不会自动替换 Benchmark 正在使用的标准。程序化调用 `PaperRubricOptimizer.revise` 也支持上面的开放材料。

## 数据回流

[data_feedback.py](../src/kochab/data_feedback.py) 从真实使用的 `UsageRecord` 出发，保留轨迹和反馈，提供两个独立出口。

- `DataCurator.regression`：把使用问题还原为可复现任务；证据不足时返回 `None`，保留原记录等待补充。可复现任务经去重和复核后进入新的 Benchmark 版本。
- `DataCurator.prepare`：筛选、清洗并转换学习材料，返回 `PreparedData`，记录来源、样本与处理理由。没有保留材料时返回空样本并说明原因。

成功轨迹不自动成为训练样本，失败也不必全部丢弃。论文示例根据人类标记检查工具回放、提取回归任务，保留选中步骤的完整输入与响应，去重后导出训练样本；新一轮评测可显式导入回归任务。这里已经规定数据出口，模型训练由外部系统承接，核心不实现训练框架。
