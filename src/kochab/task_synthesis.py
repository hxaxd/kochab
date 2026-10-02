"""任务合成协议：根据需求提出新题，先审核有效性，再实测难度。"""
from dataclasses import dataclass, replace
from typing import Protocol

from kochab.benchmark import Benchmark, BenchmarkRunner, require_evaluation
from kochab.records import Artifact, Evaluation, StopReason, Task


@dataclass(frozen=True)
class TaskProposal:
    task: Task  # 给执行 Agent 使用的新任务。
    parents: tuple[str, ...]  # 指出由哪些现有任务派生，便于检查覆盖和近重复。
    reason: str  # 描述出题意图，例如希望补足哪种边界条件。
    reference: Artifact  # 私有答案或验证依据，不能放进执行者可见输入。
    evidence: tuple[Artifact, ...] = ()  # 保存生成记录等可审计材料。


@dataclass(frozen=True)
class TaskReview:
    accepted: bool  # 表示候选是否满足进入 Benchmark 的有效性要求。
    reason: str  # 记录通过、拒绝或无法确认的理由。
    evidence: tuple[Artifact, ...] = ()  # 引用实际审核依据。


class TaskSynthesizer(Protocol):
    def propose(self, benchmark: Benchmark, feedback: Evaluation | None, *,
                count: int) -> tuple[TaskProposal, ...]:
        """根据开发任务和执行反馈提出新挑战；不读取封存测试。"""
        # 候选难度最终由固定 Agent 在任务上的表现决定，而不是由出题者自称。
        ...


class TaskValidator(Protocol):
    def validate(self, proposal: TaskProposal, benchmark: Benchmark) -> TaskReview:
        """在入集前检查关联性、可复现性和能否验证。"""
        # 审核候选有效并不等于证明了它更难，入集后仍要真实试跑。
        ...


class BenchmarkEditor(Protocol):
    def admit(self, benchmark: Benchmark, proposal: TaskProposal, review: TaskReview) -> Benchmark:
        """保存入集依据并产生新清单；只追加这一题，保留其他评测条件。"""
        # 清单存在哪里、如何编码，由领域实现决定；私有参考解不交给执行 Agent。
        ...


@dataclass(frozen=True)
class TaskAdmission:
    proposal: TaskProposal  # 接受与拒绝的候选都保留。
    review: TaskReview  # 内容审核的结论；入集操作是否成功另看 error。
    error: str | None = None  # 清单构造失败时不更新当前 Benchmark。


@dataclass(frozen=True)
class ExpansionResult:
    benchmark: Benchmark  # 包含本批成功入集的任务。
    candidates: tuple[TaskAdmission, ...]  # 顺序保留审核与入集记录。


def expand_benchmark(benchmark: Benchmark, feedback: Evaluation | None,
                     synthesizer: TaskSynthesizer, validator: TaskValidator,
                     editor: BenchmarkEditor, *, count: int) -> ExpansionResult:
    """生成至多 count 个候选，逐题审核并追加到 Benchmark 清单。

    审核始终面对本批最新清单，因此能检查批内重复。入集后核对旧题及
    环境、工具、验证器均未改变；失败候选仍进入 candidates 留待检查。
    本函数只保证题目入集有效性，实际难度由后续运行衡量。
    """
    if count < 1 or (feedback is not None and feedback.benchmark != benchmark.definition):
        raise ValueError("Use a positive count and feedback from this benchmark.")
    proposals = synthesizer.propose(benchmark, feedback, count=count)
    if len(proposals) > count:
        raise ValueError("Synthesizer exceeded the candidate budget.")
    current, records = benchmark, []
    for proposal in proposals:
        # 用当前清单审核；它可能已经包含本批前面接纳的候选。
        try:
            review = (TaskReview(False, "Duplicate task ID.")
                      if any(t.id == proposal.task.id for t in current.tasks)
                      else validator.validate(proposal, current))
        except Exception as exc:
            review = TaskReview(False, f"Review error ({type(exc).__name__}): {exc}")
        entry = TaskAdmission(proposal, review)
        if review.accepted:
            try:
                expanded = editor.admit(current, proposal, review)
                # 题目生长不能暗中删除旧题、改环境或换评分标准。
                if (expanded.definition == current.definition
                        or expanded.tasks != (*current.tasks, proposal.task)
                        or expanded.environment is not current.environment
                        or expanded.tools != current.tools or expanded.verifiers != current.verifiers):
                    raise ValueError("Admission must append one task under unchanged evaluation conditions.")
                current = expanded
            except Exception as exc:
                entry = replace(entry, error=f"{type(exc).__name__}: {exc}")
        records.append(entry)
    return ExpansionResult(current, tuple(records))


@dataclass(frozen=True)
class SynthesisRound:
    baseline: Evaluation  # 本轮出题依据。
    expansion: ExpansionResult | None = None  # 本轮审核与新清单，复测失败也保留。
    evaluation: Evaluation | None = None  # 固定 Agent 在新题集上的结果。
    error: str | None = None  # 生成或复测异常。


@dataclass(frozen=True)
class TaskSynthesisResult:
    benchmark: Benchmark  # 与 evaluation 匹配的最后一个已完成评测的版本。
    evaluation: Evaluation
    rounds: tuple[SynthesisRound, ...]
    stop_reason: StopReason


def synthesize_tasks(runner: BenchmarkRunner, benchmark: Benchmark, baseline: Evaluation,
                     synthesizer: TaskSynthesizer, validator: TaskValidator,
                     editor: BenchmarkEditor, *, count: int, rounds: int) -> TaskSynthesisResult:
    """用固定 Agent 反复扩充题集，并把每轮实测结果用于下一轮出题。

    每轮先合成和入集，再运行扩充后的清单。只有完整复测成功，返回的
    benchmark 和 evaluation 才一起更新；失败时新清单保留在轮次记录，
    返回值仍是上一对相互匹配的已评测版本。
    """
    if count < 1 or rounds < 1:
        raise ValueError("Use positive candidate and round budgets.")
    require_evaluation(baseline, benchmark, baseline.agent)
    current, result, records, stop = benchmark, baseline, [], "budget_exhausted"
    for _ in range(rounds):
        # result 是上一轮的真实运行反馈，出题者可据此找覆盖缺口。
        entry = SynthesisRound(result)
        try:
            expansion = expand_benchmark(current, result, synthesizer, validator, editor, count=count)
            entry = replace(entry, expansion=expansion)
            if expansion.benchmark.definition == current.definition:
                stop = "error" if any(c.error for c in expansion.candidates) else "no_candidates"
            else:
                trial = runner.run(baseline.agent, expansion.benchmark)
                entry = replace(entry, evaluation=trial)
                require_evaluation(trial, expansion.benchmark, baseline.agent)
                # 成功完成复测之后，才同时更新题集和对应反馈。
                current, result = expansion.benchmark, trial
        except Exception as exc:
            entry = replace(entry, error=f"{type(exc).__name__}: {exc}")
            stop = "error"
        records.append(entry)
        if stop != "budget_exhausted":
            break
    return TaskSynthesisResult(current, result, tuple(records), stop)
