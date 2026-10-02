"""A frozen paper and a fresh reading session for every task."""
from typing import Mapping

from kochab.benchmark import Tool
from kochab.records import Artifact

from .artifacts import ArtifactStore


# Agent 可见的两个动作及参数格式；是否允许由 Session.call 再次检查。
TOOLS = (
    Tool("read_page", "Read a paper page (numbered from 1).", {
        "type": "object", "properties": {"page": {"type": "integer", "minimum": 1}},
        "required": ["page"], "additionalProperties": False,
    }),
    Tool("search", "Find text in the paper; returns matching page numbers and excerpts.", {
        "type": "object", "properties": {"query": {"type": "string", "minLength": 1}},
        "required": ["query"], "additionalProperties": False,
    }),
)


class PaperEnvironment:
    """将固定论文快照转换为一个全新的阅读会话。"""

    def __init__(self, artifacts: ArtifactStore):
        # 环境只保存快照仓库的引用，不持有可变的论文文本副本。
        self.artifacts = artifacts

    def reset(self, initial_state: Artifact, *, seed: int) -> "PaperSession":
        # 每次重置都重新解析初始条件，并提前拒绝无法正常阅读的论文。
        paper = self.artifacts.get(initial_state)
        if not paper["pages"] or any(not isinstance(p, str) or not p.strip() for p in paper["pages"]):
            raise ValueError("Every paper page must have checked, non-empty text.")
        # 每个任务都拿到独立事件列表，避免状态泄漏到下一个任务。
        return PaperSession(self.artifacts, initial_state, seed)


class PaperSession:
    """记录一篇论文的观察、工具调用和可重放状态。"""

    def __init__(self, artifacts: ArtifactStore, paper: Artifact, seed: int):
        # paper 指向不可变快照，seed 随会话保留以便对照环境设置。
        self.artifacts, self.paper, self.seed = artifacts, paper, seed
        # 所有可见操作都追加在同一个列表，最终随轨迹一并保存。
        self.events: list[dict] = []
        # 会话关闭后拒绝后续操作，检查资源生命周期是否正确。
        self.closed = False

    def _paper(self):
        # 让每个公开操作共享同一关闭检查和快照读取方式。
        if self.closed:
            raise RuntimeError("The reading session is closed.")
        return self.artifacts.get(self.paper)

    def observe(self) -> object:
        # Agent 只看到标题和页数，不会一次获得隐藏的完整论文内容。
        paper = self._paper()
        result = {"title": paper["title"], "page_count": len(paper["pages"])}
        # 把初次观察写入轨迹，这样之后可与重放结果核对。
        self.events.append({"observation": result.copy()})
        return result

    def call(self, tool: str, arguments: Mapping[str, object]) -> object:
        # 获取快照文本；实际返回仍按 Agent 每次请求的动作决定。
        pages = self._paper()["pages"]
        if tool == "read_page":
            # 强制只收整数页码，避免 bool 或额外参数绕过调用约束。
            page = arguments.get("page")
            if set(arguments) != {"page"} or type(page) is not int or not 1 <= page <= len(pages):
                raise ValueError("Invalid page number or arguments.")
            result = {"page": page, "text": pages[page - 1]}
        elif tool == "search":
            # 搜索使用大小写无关的简单匹配，并保留命中页码与周边文字。
            query = arguments.get("query")
            if set(arguments) != {"query"} or not isinstance(query, str) or not query.strip():
                raise ValueError("Search requires a non-empty query.")
            result = []
            for i, page in enumerate(pages, 1):
                position = page.lower().find(query.lower())
                if position >= 0:
                    result.append({"page": i, "excerpt": page[max(0, position - 80):position + 240]})
        else:
            # 不在工具清单中的名称意味着无效动作，不静默返回空结果。
            raise ValueError(f"Unknown tool: {tool}")
        # 再经内容存储复制返回值，调用者不能反过来篡改已记录证据。
        self.events.append(self.artifacts.get(self.artifacts.put({
            "tool": tool, "arguments": dict(arguments), "result": result,
        })))
        return result

    def snapshot(self) -> Artifact:
        # 状态包含论文引用、seed 和截至当前时刻的全部事件。
        self._paper()
        return self.artifacts.put({"paper": self.paper.ref, "seed": self.seed, "events": self.events})

    def close(self) -> None:
        # 关闭不删除历史；之后的访问由 _paper 统一拒绝。
        self.closed = True
