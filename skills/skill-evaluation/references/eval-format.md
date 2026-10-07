# 评测记录

角色参考来自 Anthropic skill-creator，可由当前执行者完成；角色名称本身不要求创建子智能体。独立对照或盲评只有在上下文、输入和评分条件确实独立时才如此标注。

在当前任务工作目录保存 `evals.json`：skill_name、评测目标、各 case 的 id、prompt、input_files 和 expected_outcomes。结果可按 `iteration-1/eval-1/with_skill/run-1/` 与 `without_skill/run-1/` 组织；改进旧技能时后一条件可叫 old_skill。每次运行保存 outputs/、过程记录和实际配置。输入副本可以共享，只读；产物分别保存。

每个 run 的 grading.json 包含：

```json
{
  "status": "completed",
  "expectations": [
    {"text": "输出保留全部输入记录且数值正确", "passed": true, "evidence": "产物与输入逐条核对一致"}
  ],
  "summary": {"passed": 1, "failed": 0, "total": 1, "pass_rate": 1.0}
}
```

status 可为 completed、failed 或 not_run。passed 可为 true、false；证据不足用 null，并解释原因。汇总脚本根据真实条目重算通过率，未知不算通过。耗时和用量单独保存在 timing.json，使用 total_duration_seconds、total_tokens；未记录的字段可以省略。

已完成记录的汇总：

```powershell
python 'C:\Users\hxaxd\.agents\skills\skill-evaluation\scripts\summarize.py' '.\iteration-1' --skill-name '目标技能'
```

本地结果页：

```powershell
python 'C:\Users\hxaxd\.agents\skills\skill-evaluation\eval-viewer\generate_review.py' '.\iteration-1' --skill-name '目标技能' --benchmark '.\iteration-1\benchmark.json' --static '.\outputs\技能评测.html'
```

静态页的反馈下载需要用户保存，不自动写回评测目录。交互服务仅绑定本机环回地址，端口占用时选择空闲端口，不结束已有进程。结果页会包含所选目录的产物，分享前确认这些产物在分享范围内。

实际模型运行与委派入口见全局 local-agent-delegation 约定；本技能不附带默认调用 Claude 或默认并发执行的脚本。普通 skill-creator 创建与 review-skill-writing 审阅继续使用原有入口。
