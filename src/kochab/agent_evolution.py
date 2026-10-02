"""Agent 自进化的最小协议：根据证据提案，再根据复测决定是否保留。"""
from dataclasses import dataclass, replace
from typing import Protocol

from kochab.benchmark import Benchmark, BenchmarkRunner, require_evaluation
from kochab.records import Artifact, Evaluation, StopReason


@dataclass(frozen=True)
class AgentProposal:
    candidate: Artifact  # 候选 Agent 的固定版本，例如提示词和模型配置。
    reason: str  # 说明修改针对什么失败，以及为什么这样改。
    evidence: tuple[Artifact, ...]  # 指向支持归因的轨迹、判断或分析材料。


@dataclass(frozen=True)
class SelectionDecision:
    keep: bool  # 只有对照证据支持时才为 True。
    reason: str  # 记录采纳、拒绝或证据不足的依据。


class AgentEvolution(Protocol):
    def propose(self, baseline: Evaluation) -> AgentProposal:
        """根据基线失败归因并提出候选；修改者可以是人，也可以是 Agent。"""
        # Protocol 只规定输入输出，不规定具体的提示词搜索算法。
        ...

    def decide(self, baseline: Evaluation, trial: Evaluation) -> SelectionDecision:
        """在固定 Benchmark 和验证器下比较基线与候选，并检查退化。"""
        # 比较结果不要求提高单一总分，可以由领域定义采纳规则。
        ...


@dataclass(frozen=True)
class AgentRound:
    baseline: Evaluation  # 本轮开始时已采纳版本的完整结果。
    proposal: AgentProposal | None = None  # 提案失败时为空。
    trial: Evaluation | None = None  # 未运行或运行器失败时为空。
    decision: SelectionDecision | None = None  # 没有完整对照证据时不作决定。
    error: str | None = None  # 拒绝与执行异常分别记录。


@dataclass(frozen=True)
class AgentEvolutionResult:
    evaluation: Evaluation  # 始终返回最后一个已采纳版本，而非最后一个候选。
    rounds: tuple[AgentRound, ...]  # 包含未采纳和失败的尝试。
    stop_reason: StopReason  # 解释为什么不再继续搜索。


def evolve_agent(runner: BenchmarkRunner, benchmark: Benchmark, baseline: Evaluation,
                 optimizer: AgentEvolution, *, rounds: int) -> AgentEvolutionResult:
    """在同一 Benchmark 上反复提出候选 Agent、复测并决定是否采纳。

    先验证基线完整；每轮以最近一次采纳的结果为起点。候选未变、被拒绝
    或发生异常就停止，失败尝试仍保留在 rounds 中。evaluation 始终指向
    最后已采纳版本，不能把未复测或未采纳的候选当成改进结果。
    """
    if rounds < 1:
        raise ValueError("Use a positive revision budget.")
    require_evaluation(baseline, benchmark, baseline.agent)
    current, records, stop = baseline, [], "budget_exhausted"
    for _ in range(rounds):
        # 先建轮次记录；提案或运行失败时也能留下当时的基线。
        entry = AgentRound(current)
        try:
            proposal = optimizer.propose(current)
            entry = replace(entry, proposal=proposal)
            if proposal.candidate == current.agent:
                entry = replace(entry, decision=SelectionDecision(False, "Candidate is unchanged."))
                stop = "unchanged"
            else:
                trial = runner.run(proposal.candidate, benchmark)
                entry = replace(entry, trial=trial)
                # 完整性通过后才允许选择器比较两版结果。
                require_evaluation(trial, benchmark, proposal.candidate)
                decision = optimizer.decide(current, trial)
                entry = replace(entry, decision=decision)
                if decision.keep:
                    # 下一轮只基于真实采纳的版本继续修改。
                    current = trial
                else:
                    stop = "rejected"
        except Exception as exc:
            entry = replace(entry, error=f"{type(exc).__name__}: {exc}")
            stop = "error"
        records.append(entry)
        if stop != "budget_exhausted":
            break
    return AgentEvolutionResult(current, tuple(records), stop)
