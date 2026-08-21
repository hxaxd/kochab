from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Plugins:
    """Minimal extension hooks; defaults preserve the unmodified loop."""

    compress: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] = field(
        default=lambda messages: messages
    )
    after_step: Callable[[list[dict[str, Any]]], None] = field(default=lambda messages: None)
