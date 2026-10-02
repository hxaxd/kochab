"""Benchmark 把任务、环境、工具和验证器绑定成可重复评测的单元。"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from kochab.records import Artifact, ArtifactStore, CaseResult, Evaluation, Judgment, Task, Trace


@dataclass(frozen=True)
class Tool:
    name: str  # Agent 调用时使用的稳定名称。
    description: str  # 向 Agent 解释工具的用途和行为。
    parameters: Mapping[str, object]  # 参数结构，例如 JSON Schema；执行由 Session 承担。


class Session(Protocol):
    # observe 只返回当前任务允许 Agent 看见的状态。
    def observe(self) -> object: ...

    # call 把一次行动交给环境执行，并返回可记录的观察结果。
    def call(self, tool: str, arguments: Mapping[str, object]) -> object: ...

    # snapshot 固定当前环境状态，便于重放和事后检查。
    def snapshot(self) -> Artifact: ...

    # close 释放本轮会话占用的资源，避免任务间状态泄漏。
    def close(self) -> None: ...


class Environment(Protocol):
    def reset(self, initial_state: Artifact, *, seed: int) -> Session:
        """从给定状态和随机种子建立隔离会话；相同动作序列应复现状态变化。"""
        # 由领域实现决定如何冻结网络、时钟等外部依赖。
        ...


class Agent(Protocol):
    def run(self, problem: Artifact, tools: tuple[Tool, ...], session: Session) -> Artifact:
        """给定问题和工具后完成任务；评测器负责保存执行轨迹。"""
        # Agent 通过 Session 观察和行动，不直接改写环境状态。
        ...


class Verifier(Protocol):
    definition: Artifact  # 验证器配置版本，包含所用 Rubric 等判定条件。

    def verify(self, trace: Trace) -> Judgment:
        """根据已保存的执行证据判断，并以 definition 标明所用标准版本。"""
        ...


@dataclass(frozen=True)
class Benchmark:
    definition: Artifact  # 清单版本，记录覆盖范围、数据划分、预算和指标。
    tasks: tuple[Task, ...]  # 可运行的任务及其初始状态。
    environment: Environment  # 为每个任务创建可重置的独立会话。
    tools: tuple[Tool, ...]  # Agent 在此 Benchmark 中可以使用的动作。
    verifiers: tuple[Verifier, ...]  # 根据同一条执行轨迹给出一种或多种判断。


class BenchmarkRunner(Protocol):
    def run(self, agent: Artifact, benchmark: Benchmark) -> Evaluation:
        """解析 Agent 版本，逐任务重置、记录、验证，最后关闭会话。"""
        # 评测条件由 Benchmark 固定，输出 Evaluation 保留逐任务结果和证据。
        ...


class AgentFactory(Protocol):
    def create(self, definition: Artifact, record: Callable[[object], None]) -> Agent:
        """解析固定配置并创建执行者，通过 record 保存模型输入输出等内部事件。"""
        # 环境观察和工具调用由运行器记录，Agent 只补充内部活动。
        ...


class _RecordingSession:
    """拦截 Agent 的观察和行动，将输入、结果与异常按发生顺序写入轨迹。

    包装层不改变领域会话的行为；领域会话无需实现额外的 events 属性。
    """

    def __init__(self, session: Session, events: list[object]):
        self.session, self.events = session, events

    def observe(self) -> object:
        value = self.session.observe()
        # 保存观察当时的值；Agent 后续改动返回对象也不能改写历史。
        self.events.append({"observation": deepcopy(value)})
        return value

    def call(self, tool: str, arguments: Mapping[str, object]) -> object:
        # 即便工具抛错也保留尝试，避免失败动作从轨迹里消失。
        event = {"tool": tool, "arguments": deepcopy(dict(arguments))}
        self.events.append(event)
        try:
            value = self.session.call(tool, arguments)
            event["result"] = deepcopy(value)
            return value
        except Exception as exc:
            event["error"] = f"{type(exc).__name__}: {exc}"
            raise

    def snapshot(self) -> Artifact:
        return self.session.snapshot()

    def close(self) -> None:
        self.session.close()


def run_benchmark(agent: Artifact, benchmark: Benchmark, *, agents: AgentFactory,
                  artifacts: ArtifactStore) -> Evaluation:
    """运行固定版本的 Agent，并返回每道题的完整轨迹和判断。

    每题独立重置环境，记录 Agent 内部事件与会话交互，再取终态并关闭会话。
    执行、快照或关闭失败时仍保存错误轨迹；一个验证器失败不会阻断其他
    验证器或下一道题。返回值始终按 Benchmark 中的任务顺序排列。
    """
    if len({task.id for task in benchmark.tasks}) != len(benchmark.tasks):
        raise ValueError("Benchmark task IDs must be unique.")
    cases = []
    for task in benchmark.tasks:
        # 每题新建事件缓冲和会话，避免跨题混入观察或工具记录。
        events: list[object] = []
        session, final_state, result = None, None, None
        errors = []
        try:
            session = benchmark.environment.reset(task.initial_state, seed=task.seed)
            # 拷贝事件，防止后续原地修改污染已经记录的历史。
            actor = agents.create(agent, lambda event: events.append(deepcopy(event)))
            result = actor.run(task.problem, benchmark.tools, _RecordingSession(session, events))
            if not isinstance(result, Artifact):
                raise TypeError("Agent must return an Artifact.")
        except Exception as exc:
            errors.append({"type": type(exc).__name__, "message": str(exc), "stage": "execution"})
        finally:
            if session is not None:
                try:
                    final_state = session.snapshot()
                except Exception as exc:
                    errors.append({"type": type(exc).__name__, "message": str(exc), "stage": "snapshot"})
                finally:
                    # 快照失败也必须释放资源；清理错误单独留下证据。
                    try:
                        session.close()
                    except Exception as exc:
                        errors.append({"type": type(exc).__name__, "message": str(exc), "stage": "close"})
        if errors:
            events.append({"termination": "error", "error": errors[0], "errors": errors})
        else:
            events.append({"termination": "completed"})
        if not isinstance(result, Artifact):
            # 错误也需有可引用的结果，供验证器和后续归因读取。
            result = artifacts.put({"error": errors[0] if errors else {"message": "Agent returned no result"}})
        trace = Trace(task, agent, artifacts.put(events), result, final_state)
        judgments = []
        for verifier in benchmark.verifiers:
            # 所有验证器查看同一条冻结轨迹，单个验证器异常只影响自己的判断。
            try:
                judgment = verifier.verify(trace)
                if judgment.verifier != verifier.definition:
                    raise ValueError("Verifier returned a judgment under a different version.")
                judgments.append(judgment)
            except Exception as exc:
                judgments.append(Judgment(verifier.definition, {"status": "error"},
                                          f"{type(exc).__name__}: {exc}", (trace.result,)))
        cases.append(CaseResult(trace, tuple(judgments)))
    return Evaluation(benchmark.definition, agent, tuple(cases))


def require_evaluation(evaluation: Evaluation, benchmark: Benchmark, agent: Artifact) -> None:
    """核对评测版本，以及逐题、逐验证器的完整性与顺序。

    改进循环用它拦下错版本和缺项的复测，避免拿不同条件的结果做选择。
    """
    expected = tuple(verifier.definition for verifier in benchmark.verifiers)
    if (evaluation.benchmark != benchmark.definition or evaluation.agent != agent
            or tuple(case.trace.task for case in evaluation.cases) != benchmark.tasks
            or any(case.trace.agent != agent or tuple(j.verifier for j in case.judgments) != expected
                   for case in evaluation.cases)):
        raise ValueError("Evaluation must contain every task and verifier from the requested versions.")
