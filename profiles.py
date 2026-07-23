"""DecodeProfile 档案池：JSON 存取（内置「默认」不可删可恢复 + 用户增删改）。

存储位置：paths.data_dir() / profiles.json。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from decoder import DecodeProfile
from paths import data_dir

logger = logging.getLogger(__name__)

BUILTIN_NAME = "默认"


class ProfileStore:
    """档案池。db_path 可注入（测试用 tmp 路径）。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else data_dir() / "profiles.json"
        self._profiles: dict[str, DecodeProfile] = {}
        self._load()

    def _load(self):
        self._profiles = {BUILTIN_NAME: DecodeProfile()}
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for name, d in data.items():
                    if name != BUILTIN_NAME:
                        self._profiles[name] = DecodeProfile.from_dict(d)
            except Exception:  # noqa: BLE001
                logger.exception("档案池读取失败: %s", self.path)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {n: p.to_dict() for n, p in self._profiles.items()
                   if n != BUILTIN_NAME}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def names(self) -> list[str]:
        return [BUILTIN_NAME] + sorted(n for n in self._profiles if n != BUILTIN_NAME)

    def get(self, name: str) -> DecodeProfile:
        return self._profiles.get(name) or DecodeProfile()

    def is_builtin(self, name: str) -> bool:
        return name == BUILTIN_NAME

    def save(self, name: str, profile: DecodeProfile) -> None:
        """另存为/覆盖。内置「默认」不可写。"""
        if not name or name == BUILTIN_NAME:
            raise ValueError("内置「默认」档案不可修改，请另存为新名称")
        self._profiles[name] = profile
        self._save()

    def rename(self, old: str, new: str) -> None:
        if self.is_builtin(old):
            raise ValueError("内置「默认」档案不可重命名")
        if old not in self._profiles:
            raise ValueError(f"档案不存在: {old}")
        if not new or new == BUILTIN_NAME or new in self._profiles:
            raise ValueError(f"名称不可用: {new}")
        self._profiles[new] = self._profiles.pop(old)
        self._save()

    def delete(self, name: str) -> None:
        if self.is_builtin(name):
            raise ValueError("内置「默认」档案不可删除")
        self._profiles.pop(name, None)
        self._save()
