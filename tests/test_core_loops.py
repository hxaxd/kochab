"""用不依赖论文示例的替身验证通用循环；不代表真实模型的改进效果。"""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest

from kochab.agent_evolution import AgentProposal, SelectionDecision, evolve_agent
from kochab.benchmark import Benchmark, Tool, run_benchmark
from kochab.records import Artifact, CaseResult, Evaluation, Judgment, Task, Trace
from kochab.rubric import RubricAssessment, RubricCase, RubricRevision, evolve_rubric
from kochab.task_synthesis import TaskProposal, TaskReview, expand_benchmark, synthesize_tasks


class MemoryStore:
    """测试用不可变快照仓库，不依赖示例的文件格式和哈希约定。"""

    def __init__(self):
        self.values = []

    def put(self, value):
        self.values.append(deepcopy(value))
        return Artifact(str(len(self.values) - 1))

    def get(self, artifact):
        return deepcopy(self.values[int(artifact.ref)])


class CoreLoopTests(unittest.TestCase):
    """验证接口组合、证据保留、候选选择和失败边界。"""

    def setUp(self):
        self.store = MemoryStore()
        self.agent, self.candidate = Artifact("agent"), Artifact("candidate")
        self.task = Task("one", Artifact("problem"), Artifact("initial"), 7)
        self.verifier = SimpleNamespace(definition=Artifact("verifier"))
        self.benchmark = Benchmark(Artifact("benchmark"), (self.task,), None, (), (self.verifier,))
        self.baseline = self.evaluation(self.agent, self.benchmark)

    def evaluation(self, agent, benchmark):
        # 每个结果明确绑定任务、Agent 和验证器版本。
        return Evaluation(benchmark.definition, agent, tuple(
            CaseResult(Trace(task, agent, Artifact("events"), Artifact("result"), task.initial_state),
                       tuple(Judgment(v.definition, True, "Offline check") for v in benchmark.verifiers))
            for task in benchmark.tasks))

    def test_runner_records_without_session_events_and_closes_every_task(self):
        """领域 Session 不提供 events，核心也能记录观察、动作和模型事件。"""
        closed, seeds, final_states = [], [], []
        def reset(initial, *, seed):
            seeds.append(seed)
            state = {"n": 0}
            def call(tool, arguments):
                state["n"] += arguments["increment"]
                return state  # 故意返回可变对象，检查记录是否冻结。
            def snapshot():
                final_states.append(state["n"])
                return self.store.put(state)
            return SimpleNamespace(observe=lambda: state, call=call, snapshot=snapshot,
                                   close=lambda: closed.append(initial))
        def create(definition, record):
            self.assertEqual(definition, self.agent)
            def run(problem, tools, session):
                session.observe()
                record({"model_input": "offline request", "model_output": "offline action"})
                session.call("add", {"increment": 1})
                session.call("add", {"increment": 2})
                return self.store.put({"done": True})
            return SimpleNamespace(run=run)
        verifier = SimpleNamespace(definition=self.verifier.definition,
                                   verify=lambda trace: Judgment(self.verifier.definition, True, "checked"))
        benchmark = replace(self.benchmark, environment=SimpleNamespace(reset=reset),
                            tasks=(self.task, replace(self.task, id="two")), verifiers=(verifier,),
                            tools=(Tool("add", "Increase counter", {}),))
        result = run_benchmark(self.agent, benchmark, agents=SimpleNamespace(create=create), artifacts=self.store)
        self.assertEqual((len(closed), seeds, final_states), (2, [7, 7], [3, 3]))
        events = self.store.get(result.cases[0].trace.events)
        self.assertEqual(events[0]["observation"], {"n": 0})
        self.assertEqual(events[2]["result"], {"n": 1})
        self.assertEqual(events[-1], {"termination": "completed"})

    def test_runner_retains_reset_run_snapshot_and_close_failures(self):
        """每个资源边界的异常都留下轨迹，且已有会话总会尝试关闭。"""
        def fail():
            raise RuntimeError("offline failure")
        for stage in ("reset", "run", "snapshot", "close", "invalid_result"):
            with self.subTest(stage=stage):
                closed = []
                def close():
                    closed.append(True)
                    if stage == "close":
                        fail()
                def reset(initial, *, seed):
                    if stage == "reset":
                        fail()
                    return SimpleNamespace(snapshot=fail if stage == "snapshot" else lambda: Artifact("final"),
                                           close=close)
                def run(*args):
                    if stage == "run":
                        fail()
                    return None if stage == "invalid_result" else Artifact("output")
                benchmark = replace(self.benchmark, environment=SimpleNamespace(reset=reset), verifiers=())
                factory = SimpleNamespace(create=lambda *args: SimpleNamespace(run=run))
                result = run_benchmark(self.agent, benchmark, agents=factory, artifacts=self.store)
                trace = result.cases[0].trace
                self.assertEqual(self.store.get(trace.events)[-1]["termination"], "error")
                self.assertEqual(len(closed), 0 if stage == "reset" else 1)
                if stage in ("reset", "snapshot"):
                    self.assertIsNone(trace.final_state)

    def test_verifier_error_does_not_discard_other_judgments(self):
        """错误的验证器身份与异常都转为错误判断，其他验证器仍执行。"""
        def fail(trace):
            raise RuntimeError("judge unavailable")
        verifiers = (SimpleNamespace(definition=Artifact("bad"), verify=fail),
                     SimpleNamespace(definition=Artifact("wrong"),
                                     verify=lambda t: Judgment(Artifact("other"), True, "wrong version")),
                     SimpleNamespace(definition=Artifact("good"),
                                     verify=lambda t: Judgment(Artifact("good"), [True, False], "vector")))
        session = SimpleNamespace(snapshot=lambda: Artifact("final"), close=lambda: None)
        benchmark = replace(self.benchmark, verifiers=verifiers,
                            environment=SimpleNamespace(reset=lambda *a, **k: session))
        factory = SimpleNamespace(create=lambda *a: SimpleNamespace(run=lambda *a: Artifact("output")))
        result = run_benchmark(self.agent, benchmark, agents=factory, artifacts=self.store)
        self.assertEqual([j.value for j in result.cases[0].judgments],
                         [{"status": "error"}, {"status": "error"}, [True, False]])

    def test_agent_keeps_last_accepted_candidate_and_records_rejection(self):
        """接受第一版、拒绝第二版，第三轮不会继续运行。"""
        proposals = iter((self.candidate, Artifact("bad")))
        optimizer = SimpleNamespace(propose=lambda baseline: AgentProposal(next(proposals), "change", ()),
                                    decide=lambda before, after: SelectionDecision(after.agent == self.candidate, "compare"))
        result = evolve_agent(SimpleNamespace(run=self.evaluation), self.benchmark, self.baseline, optimizer, rounds=3)
        self.assertEqual(result.evaluation.agent, self.candidate)
        self.assertEqual(result.stop_reason, "rejected")
        self.assertEqual(len(result.rounds), 2)
        self.assertEqual(result.rounds[1].baseline.agent, self.candidate)

    def test_agent_rejects_incomplete_or_misidentified_trials_before_selection(self):
        """复测条件错误时，不能让宽松选择器把它采纳。"""
        trial = self.evaluation(self.candidate, self.benchmark)
        for invalid in (replace(trial, cases=()), replace(trial, agent=self.agent),
                        replace(trial, benchmark=Artifact("other")),
                        replace(trial, cases=(replace(trial.cases[0], judgments=()),))):
            with self.subTest(invalid=invalid):
                optimizer = SimpleNamespace(propose=lambda b: AgentProposal(self.candidate, "change", ()),
                                            decide=lambda *args: self.fail("Must validate before selection"))
                result = evolve_agent(SimpleNamespace(run=lambda *a: invalid), self.benchmark,
                                      self.baseline, optimizer, rounds=2)
                self.assertEqual(result.stop_reason, "error")
                self.assertEqual(result.evaluation, self.baseline)
                self.assertEqual(result.rounds[0].trial, invalid)

    def test_agent_unchanged_candidate_does_not_call_runner(self):
        optimizer = SimpleNamespace(propose=lambda b: AgentProposal(self.agent, "no change", ()))
        result = evolve_agent(SimpleNamespace(run=lambda *a: self.fail("Do not rerun unchanged agent")),
                              self.benchmark, self.baseline, optimizer, rounds=2)
        self.assertEqual(result.stop_reason, "unchanged")

    def editor(self):
        # 最小领域实现只追加任务并生成清单版本。
        return SimpleNamespace(admit=lambda benchmark, proposal, review: replace(
            benchmark, tasks=(*benchmark.tasks, proposal.task), definition=Artifact(benchmark.definition.ref + "+")))

    def test_synthesis_feeds_new_evaluation_to_next_round_with_fixed_agent(self):
        sources = []
        def propose(benchmark, feedback, *, count):
            sources.append(feedback)
            task = replace(self.task, id=f"new-{len(sources)}")
            return (TaskProposal(task, (self.task.id,), "new coverage", Artifact("private")),)
        result = synthesize_tasks(SimpleNamespace(run=self.evaluation), self.benchmark, self.baseline,
                                  SimpleNamespace(propose=propose),
                                  SimpleNamespace(validate=lambda *a: TaskReview(True, "valid")),
                                  self.editor(), count=1, rounds=2)
        self.assertEqual([len(source.cases) for source in sources], [1, 2])
        self.assertTrue(all(source.agent == self.agent for source in sources))
        self.assertEqual(len(result.evaluation.cases), 3)
        self.assertEqual(result.evaluation.benchmark, result.benchmark.definition)

    def test_failed_expansion_evaluation_retains_matching_baseline_and_candidate(self):
        proposal = TaskProposal(replace(self.task, id="new"), (), "new coverage", Artifact("private"))
        result = synthesize_tasks(SimpleNamespace(run=lambda *a: replace(self.baseline, cases=())),
                                  self.benchmark, self.baseline, SimpleNamespace(propose=lambda *a, **k: (proposal,)),
                                  SimpleNamespace(validate=lambda *a: TaskReview(True, "valid")),
                                  self.editor(), count=1, rounds=2)
        self.assertEqual(result.stop_reason, "error")
        self.assertEqual(result.benchmark, self.benchmark)
        self.assertEqual(result.evaluation, self.baseline)
        self.assertEqual(len(result.rounds[0].expansion.benchmark.tasks), 2)

    def test_admission_guards_versions_conditions_and_duplicate_ids(self):
        proposal = TaskProposal(replace(self.task, id="new"), (), "coverage", Artifact("private"))
        generator = SimpleNamespace(propose=lambda *a, **k: (proposal, proposal))
        validator = SimpleNamespace(validate=lambda *a: TaskReview(True, "valid"))
        result = expand_benchmark(self.benchmark, None, generator, validator, self.editor(), count=2)
        self.assertEqual(len(result.benchmark.tasks), 2)
        self.assertFalse(result.candidates[1].review.accepted)
        for edit in (lambda b, p, r: replace(b, tasks=(*b.tasks, p.task)),
                     lambda b, p, r: replace(b, definition=Artifact("new"), tasks=(p.task,)),
                     lambda b, p, r: replace(b, definition=Artifact("new"), tasks=(*b.tasks, p.task), verifiers=())):
            with self.subTest(edit=edit):
                invalid = expand_benchmark(self.benchmark, None, generator, validator,
                                           SimpleNamespace(admit=edit), count=2)
                self.assertEqual(invalid.benchmark, self.benchmark)
                self.assertIsNotNone(invalid.candidates[0].error)

    def test_rubric_accepts_unlabeled_pairs_expert_prose_preferences_and_multiple_standards(self):
        """无标签和非数值材料也能完整走过修订、复评、采纳。"""
        trace = self.baseline.cases[0].trace
        pair = (trace, replace(trace, agent=self.candidate, result=Artifact("second")))
        old, new = Artifact("rubric-old"), Artifact("rubric-new")
        cases = (
            RubricCase(traces=pair, instruction="这两条轨迹有争议，调查遗漏的标准。"),
            RubricCase(traces=pair, feedback=(self.store.put("专家：第一条保留了适用条件，第二条没有。"),)),
            RubricCase(traces=pair, feedback=(self.store.put({"preferred": 0}),)),
            RubricCase(rubrics=(old, Artifact("alternative")), instruction="比较两版标准的证据要求。"),
        )
        for case in cases:
            with self.subTest(case=case):
                seen, evaluated = [], []
                def revise(rubric, materials):
                    seen.append(materials)
                    return RubricRevision(new, "Offline candidate")
                def assess(rubric, materials):
                    evaluated.append(materials)
                    return RubricAssessment(rubric, reason="Offline investigation", status="ready" if rubric == old else "complete")
                result = evolve_rubric(old, (case,), SimpleNamespace(revise=revise), SimpleNamespace(assess=assess),
                                       SimpleNamespace(decide=lambda *a: SelectionDecision(True, "supported")), rounds=2)
                self.assertEqual(result.rubric, new)
                self.assertEqual(result.stop_reason, "complete")
                self.assertEqual(seen, [(case,)])
                self.assertEqual(evaluated, [(case,), (case,)])

    def test_rubric_original_evidence_survives_multiple_rounds(self):
        """新调查结果作为补充，不能把最初的专家意见或争议覆盖掉。"""
        original = RubricCase(instruction="比较两种要求的冲突")
        finding = RubricCase(feedback=(self.store.put("查到新的证据"),))
        old = Artifact("r0")
        versions = iter((Artifact("r1"), Artifact("r2")))
        seen = []
        def revise(rubric, cases):
            seen.append(cases)
            return RubricRevision(next(versions), "clarify")
        assessor = SimpleNamespace(assess=lambda rubric, cases: RubricAssessment(rubric, (finding,)))
        result = evolve_rubric(old, (original,), SimpleNamespace(revise=revise), assessor,
                               SimpleNamespace(decide=lambda *a: SelectionDecision(True, "accept")), rounds=2)
        self.assertEqual(seen, [(original, finding), (original, finding)])
        self.assertEqual(result.stop_reason, "budget_exhausted")
        self.assertEqual(result.rubric, Artifact("r2"))

    def test_rubric_rejection_error_and_insufficient_evidence_do_not_replace_baseline(self):
        case = RubricCase(instruction="调查争议，不预设答案")
        old, new = Artifact("old"), Artifact("new")
        for stop in ("rejected", "error", "insufficient_evidence", "unchanged"):
            with self.subTest(stop=stop):
                def assess(rubric, cases):
                    status = stop if rubric == new and stop in {"error", "insufficient_evidence"} else "ready"
                    return RubricAssessment(rubric, status=status)
                def select(*args):
                    if stop != "rejected":
                        self.fail("Cannot select unassessed or failed candidate")
                    return SelectionDecision(False, "not supported")
                revision = RubricRevision(old if stop == "unchanged" else new, "candidate")
                result = evolve_rubric(old, (case,), SimpleNamespace(revise=lambda *a: revision),
                                       SimpleNamespace(assess=assess), SimpleNamespace(decide=select), rounds=2)
                self.assertEqual(result.stop_reason, stop)
                self.assertEqual(result.rubric, old)
                self.assertEqual(result.assessment.rubric, old)
                self.assertEqual(len(result.rounds), 1)

    def test_rubric_initial_failure_and_wrong_candidate_version_are_recorded(self):
        case = RubricCase(instruction="调查")
        old, new = Artifact("old"), Artifact("new")
        def fail(*args):
            raise RuntimeError("assessor unavailable")
        initial = evolve_rubric(old, (case,), None, SimpleNamespace(assess=fail), None, rounds=1)
        self.assertEqual(initial.stop_reason, "error")
        self.assertIn("unavailable", initial.error)
        # 复评偷偷返回旧版身份时，保留提案但不得选择。
        result = evolve_rubric(old, (case,), SimpleNamespace(revise=lambda *a: RubricRevision(new, "change")),
                               SimpleNamespace(assess=lambda *a: RubricAssessment(old)), None, rounds=1)
        self.assertEqual(result.stop_reason, "error")
        self.assertEqual(result.rubric, old)
        self.assertIsNotNone(result.rounds[0].error)


if __name__ == "__main__":
    unittest.main()
