"""Rubric 改进：从开放证据提出修订，复评后由接入方决定是否采用。"""
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from kochab.agent_evolution import SelectionDecision
from kochab.records import Artifact, Judgment, StopReason, Trace


@dataclass(frozen=True)
class RubricCase:
    """一组相关材料；不要求成对轨迹、分数、偏好或专家答案必须存在。"""

    traces: tuple[Trace, ...] = ()  # 可放一条、多条或零条轨迹，顺序由调用者保留。
    judgments: tuple[Judgment, ...] = ()  # 已有判断，可来自不同评判者或标准。
    rubrics: tuple[Artifact, ...] = ()  # 需要比较的标准版本，不必等于当前版本。
    feedback: tuple[Artifact, ...] = ()  # 专家文字、偏好、争议材料等；内容格式开放。
    instruction: str = ""  # 说明材料之间的关系，例如“这两条轨迹有争议”。


@dataclass(frozen=True)
class JudgmentBatch:
    rubric: Artifact  # 本批判断共用的 Rubric 版本。
    trace: Trace  # 每次调用都针对同一条执行轨迹。
    judgments: tuple[Judgment, ...]  # 独立调用的结果，不合并成单一分数。


@dataclass(frozen=True)
class Disagreement:
    batch: JudgmentBatch  # 保存每条原始判断，便于复查分歧。
    reason: str  # 由领域逻辑说明为什么这些结果互不一致。


@dataclass(frozen=True)
class RubricRevision:
    rubric: Artifact  # 候选标准的完整新版本。
    summary: str  # 对分歧原因、修改理由和未解决问题的总结。


@dataclass(frozen=True)
class HumanReview:
    rubric: Artifact  # 经人类审核的候选版本。
    samples: tuple[RubricCase, ...]  # 同时覆盖被标记和未被标记的案例。
    reviewer: str  # 记录由谁负责最终抽检。
    accepted: bool  # 人类是否接受这版标准进入实际使用。
    notes: str  # 保留抽检发现和仍需处理的事项。


class RubricEvaluator(Protocol):
    def repeat(self, rubric: Artifact, trace: Trace, *, repeats: int) -> JudgmentBatch:
        """对固定轨迹进行至少两次独立评判；实现可并行发起这些调用。"""
        # 不能把重新运行 Agent 得到的新轨迹当成 Rubric 分歧。
        ...


class JudgmentConsistency(Protocol):
    def check(self, batch: JudgmentBatch) -> Disagreement | None:
        """按领域标准找出实质性分歧，不假设判断结果一定是数值。"""
        # 不一致时返回完整批次，才能交给另一轮调用进行归因。
        ...


class RubricOptimizer(Protocol):
    def draft(self, requirement: Artifact) -> Artifact:
        """根据任务需求和预期成功条件生成初始 Rubric。"""
        # 不确定的业务标准应列出来，不应伪装成已确认规则。
        ...

    def revise(self, rubric: Artifact, cases: tuple[RubricCase, ...]) -> RubricRevision:
        """根据轨迹比较、专家意见、争议或候选标准等材料提出完整修订。"""
        # 没有给出正确答案时应调查和说明不确定性，不能编造专家结论。
        ...


def disagreement_case(disagreement: Disagreement) -> RubricCase:
    """重复判断只是开放证据的一种来源，可直接转为普通修订案例。"""
    batch = disagreement.batch
    return RubricCase((batch.trace,), batch.judgments, (batch.rubric,),
                      instruction=disagreement.reason)


@dataclass(frozen=True)
class RubricAssessment:
    rubric: Artifact  # 被复评的确切标准版本。
    findings: tuple[RubricCase, ...] = ()  # 调查发现会作为下一轮修订材料。
    evidence: tuple[Artifact, ...] = ()  # 保存判断、调查或比较的原始记录。
    reason: str = ""  # 说明当前标准的表现和仍待解决的问题。
    status: Literal["ready", "complete", "insufficient_evidence", "error"] = "ready"
    # ready 表示可继续改进；complete 只表示当前策略决定停止，不代表标准已正确。


class RubricAssessor(Protocol):
    def assess(self, rubric: Artifact, cases: tuple[RubricCase, ...]) -> RubricAssessment:
        """在固定材料上检查标准；可比较偏好、调查争议，也可重复评判。"""
        # 证据不足时可以请求补充；不要求把所有意见转换成分数。
        ...


class RubricSelector(Protocol):
    def decide(self, baseline: RubricAssessment, trial: RubricAssessment) -> SelectionDecision:
        """依据前后复评决定是否采纳；一致性、专家偏好等标准由接入方选择。"""
        # 人类或 Agent 都可以实现；循环本身不宣称已完成专家审核。
        ...


@dataclass(frozen=True)
class RubricRound:
    baseline: RubricAssessment  # 已采纳版本的表现。
    revision: RubricRevision | None = None  # 保留修订及修改理由，即便最终拒绝。
    trial: RubricAssessment | None = None  # 同一批材料上对候选的复评。
    decision: SelectionDecision | None = None
    error: str | None = None


@dataclass(frozen=True)
class RubricEvolutionResult:
    rubric: Artifact  # 最后一个已采纳版本；失败候选不会覆盖它。
    initial: RubricAssessment | None  # 保留首次检查，包含无需修订的情况。
    assessment: RubricAssessment | None  # 当前已采纳版本的检查。
    rounds: tuple[RubricRound, ...]
    stop_reason: StopReason
    error: str | None = None  # 首次检查失败时也能返回明确错误。


def evolve_rubric(rubric: Artifact, cases: tuple[RubricCase, ...], optimizer: RubricOptimizer,
                  assessor: RubricAssessor, selector: RubricSelector, *, rounds: int) -> RubricEvolutionResult:
    """在同一批原始材料上检查、修订、复评并选择 Rubric 版本。

    输入可包含轨迹、专家意见、未裁定争议或候选标准。每轮把当前检查发现
    作为补充材料交给优化器，复评仍使用原始案例以保持可比性。只有选择器
    接受候选才更新当前标准；错误、证据不足和拒绝均保留上个已采纳版本。
    """
    if rounds < 1 or not cases:
        raise ValueError("Supply cases and a positive revision budget.")

    def assess(version: Artifact) -> RubricAssessment:
        """统一复评入口，并确认结果确实对应请求的标准版本。"""
        result = assessor.assess(version, cases)
        if result.rubric != version or result.status not in {"ready", "complete", "insufficient_evidence", "error"}:
            raise ValueError("Assessment must identify the requested rubric and a valid status.")
        return result

    try:
        # 初次检查也可能无法运行；此时没有候选和轮次，但保留错误原因。
        current = initial = assess(rubric)
    except Exception as exc:
        return RubricEvolutionResult(rubric, None, None, (), "error", f"{type(exc).__name__}: {exc}")
    records, stop = [], "budget_exhausted"
    for _ in range(rounds):
        if current.status != "ready":
            stop = current.status
            break
        entry = RubricRound(current)
        try:
            # 原始材料每轮保留；新调查结果只能补充，不能悄悄替换专家原意。
            revision = optimizer.revise(rubric, cases + current.findings)
            entry = replace(entry, revision=revision)
            if revision.rubric == rubric:
                stop = "unchanged"
            else:
                # 候选在与基线相同的原始案例上复评，避免换材料造成假提升。
                trial = assess(revision.rubric)
                entry = replace(entry, trial=trial)
                if trial.status in {"error", "insufficient_evidence"}:
                    stop = trial.status
                else:
                    decision = selector.decide(current, trial)
                    entry = replace(entry, decision=decision)
                    if decision.keep:
                        rubric, current = revision.rubric, trial
                        if current.status == "complete":
                            stop = "complete"
                    else:
                        stop = "rejected"
        except Exception as exc:
            entry = replace(entry, error=f"{type(exc).__name__}: {exc}")
            stop = "error"
        records.append(entry)
        if stop != "budget_exhausted":
            break
    return RubricEvolutionResult(rubric, initial, current, tuple(records), stop)
