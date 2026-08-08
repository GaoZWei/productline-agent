"""单次 Run 内 Tool 调用指纹和进程内调用记录。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from threading import Lock

from pydantic import BaseModel

_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# 调用指纹生成函数（根据 Tool 名和已校验参数生成不暴露原文的 SHA-256 指纹）
def build_tool_call_fingerprint(tool_name: str, tool_input: BaseModel) -> str:
    """根据稳定 Tool 名和已校验参数生成不暴露原文的 SHA-256 指纹。"""

    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("tool_name must be a non-empty string")
    if not isinstance(tool_input, BaseModel):
        raise ValueError("tool_input must be a validated Pydantic model")
    # 生成规范 JSON 字符串：类似{"arguments":{"order_id":"ORDER-003"},"tool_name":"get_order_detail"}
    canonical_payload = json.dumps(
        {
            "arguments": tool_input.model_dump(mode="json", round_trip=True),
            "tool_name": tool_name,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    # 计算 SHA-256 指纹（小写）
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class RunToolCallLedger:
    """为一个 Run 原子记录逻辑 Tool 调用且不保存原始参数。"""

    run_id: str
    _fingerprints: set[str] = field(default_factory=set, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    # 尝试占位调用指纹（不包含 I/O）
    # 如果指纹已存在且 force_refresh 为 False，返回 False。
    # 如果指纹不存在或 force_refresh 为 True，占位并返回 True。
    def try_reserve(self, fingerprint: str, *, force_refresh: bool = False) -> bool:
        """首次调用或显式刷新时占位。普通重复调用返回 False。"""

        if not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")
        if not isinstance(force_refresh, bool):
            raise ValueError("force_refresh must be a boolean")

        # 该临界区不包含 I/O。锁保证并发协程或线程不能同时通过同一指纹。
        with self._lock:
            if fingerprint in self._fingerprints and not force_refresh:
                return False
            self._fingerprints.add(fingerprint)
            return True
        
    @property
    def recorded_call_count(self) -> int:
        """返回当前 Run 已记录的不同逻辑调用数量。"""

        with self._lock:
            return len(self._fingerprints)
