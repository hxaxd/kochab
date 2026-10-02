"""核心共用的数据记录；Artifact 用引用连接实际内容，不限定内容必须是文本。"""
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Artifact:
    ref: str  # 内容或版本的稳定引用，由具体系统负责保存和解析。


class ArtifactStore(Protocol):
    def put(self, value: object) -> Artifact:
        """保存不可变快照并返回稳定引用；相同引用不能指向变化的内容。"""
        ...

    def get(self, artifact: Artifact) -> object:
        """解析已保存内容；调用者不能原地改写仓库中的快照。"""
        ...


# 停止原因与是否采用候选分开：预算耗尽不表示改进成功。
StopReason = Literal["budget_exhausted", "rejected", "unchanged", "no_candidates",
                     "complete", "insufficient_evidence", "error"]


@dataclass(frozen=True)
class Task:
    id: str  # Benchmark 内可读、稳定的任务标识。
    problem: Artifact  # 任务要求；可以是文字、交互协议或系统。
    initial_state: Artifact  # reset 时载入的环境初始条件。
    seed: int  # 固定环境随机种子，便于复现相同动作的结果。


@dataclass(frozen=True)
class Trace:
    task: Task  # 这次执行针对的任务及初始条件。
    agent: Artifact  # 实际执行者的模型、提示词和配置版本。
    events: Artifact  # 按顺序记录观察、行动、工具结果和终止原因。
    result: Artifact  # Agent 提交的产物或执行错误。
    final_state: Artifact | None  # 环境终态；初始化或快照失败时没有终态。


@dataclass(frozen=True)
class Judgment:
    verifier: Artifact  # 验证器及 Rubric 版本，保证判断可以追溯。
    value: object  # 领域自定的结果；可为标签、结构或数值。
    reason: str  # 用自然语言说明判断依据。
    evidence: tuple[Artifact, ...] = ()  # 指向支持判断的产物、轨迹或环境证据。


@dataclass(frozen=True)
class CaseResult:
    trace: Trace  # 一个任务的一次完整执行证据。
    judgments: tuple[Judgment, ...]  # 同一执行可以由多个验证器分别判断。


@dataclass(frozen=True)
class Evaluation:
    benchmark: Artifact  # 固定评测清单；变更任务或验证器时应生成新版本。
    agent: Artifact  # 本轮被测执行者版本。
    cases: tuple[CaseResult, ...]  # 按任务记录轨迹和所有判断，不只保存平均分。
