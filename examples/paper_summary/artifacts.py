"""A small content-addressed store; reports contain ordinary JSON values."""
import hashlib
import json
from copy import deepcopy

from kochab.records import Artifact


class ArtifactStore:
    """存储本例使用的不可变 JSON 快照，并用内容哈希作为引用。"""

    def __init__(self, contents: dict | None = None):
        self.contents: dict[str, object] = {}
        # 从报告恢复材料时重新计算哈希，拒绝被意外修改的内容。
        for ref, value in (contents or {}).items():
            if self.put(value).ref != ref:
                raise ValueError("Artifact content does not match its reference.")

    def put(self, value: object) -> Artifact:
        # 规范化键顺序后，同一份 JSON 内容总会得到相同的引用。
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        ref = hashlib.sha256(text.encode()).hexdigest()
        # 只保存 JSON 快照，不让调用者后续修改原对象影响轨迹。
        self.contents[ref] = json.loads(text)
        return Artifact(ref)

    def get(self, artifact: Artifact):
        # 返回副本，让读取者无法修改内容寻址存储中的原始快照。
        return deepcopy(self.contents[artifact.ref])
