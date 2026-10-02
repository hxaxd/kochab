"""真实使用的轨迹可以回归成测试任务，也可以整理成训练材料。"""
from dataclasses import dataclass
from typing import Protocol

from kochab.records import Artifact, Task, Trace


@dataclass(frozen=True)
class UsageRecord:
    trace: Trace  # 保留实际输入、动作、工具结果和最终产物，便于还原。
    feedback: Artifact  # 指向用户或审核者的反馈，不能只凭成功/失败自动猜测。


@dataclass(frozen=True)
class PreparedData:
    source: UsageRecord  # 从样本追溯回使用记录和反馈。
    samples: tuple[Artifact, ...]  # 通过筛选、清洗并转换后的训练样本。
    reason: str  # 解释筛选与转换；没有保留样本时说明原因。


class DataCurator(Protocol):
    def regression(self, usage: UsageRecord) -> Task | None:
        """把使用问题还原为可重放任务；证据不足就返回 None。"""
        # None 表示先保留记录等待补充，不把不确定事件写成测试集。
        ...

    def prepare(self, usage: UsageRecord) -> PreparedData:
        """按明确标准选择、清洗和格式化材料；一次成功不自动成为样本。"""
        # 输出样本应保留必要上下文、来源和处理理由。
        ...
