"""导出模板池：命名导出配置的 JSON 存取 + 内置预设。

存储位置：paths.data_dir() / templates.json。
一条模板 = 行模板/连接符/外模板/分组/格式/分隔符/过滤四条件。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from exporter import (DEFAULT_TEMPLATE, ExportFilter)
from paths import data_dir
from profiles import _backup_corrupt

logger = logging.getLogger(__name__)

# 内置预设（templates.json 不存在时首次写入）
BUILTIN_TEMPLATES: dict[str, dict] = {
    "默认逐行": {
        "template": DEFAULT_TEMPLATE, "joiner": "\n", "outer": "{items}",
        "group_by": "none", "format": "TXT", "delimiter": ",",
        "filter": {"types": None, "min_len": None, "max_len": None,
                   "prefix": "", "regex": ""},
    },
    "元组聚合": {
        "template": "{content}", "joiner": "','", "outer": "{'{items}'}",
        "group_by": "image", "format": "TXT", "delimiter": ",",
        "filter": {"types": None, "min_len": None, "max_len": None,
                   "prefix": "", "regex": ""},
    },
    "JSON 数组": {
        "template": "{content}", "joiner": "\n", "outer": "{items}",
        "group_by": "none", "format": "JSON", "delimiter": ",",
        "filter": {"types": None, "min_len": None, "max_len": None,
                   "prefix": "", "regex": ""},
    },
    "SQL IN": {
        "template": "{content}", "joiner": "','", "outer": "IN ('{items}')",
        "group_by": "global", "format": "TXT", "delimiter": ",",
        "filter": {"types": None, "min_len": None, "max_len": None,
                   "prefix": "", "regex": ""},
    },
}


def filter_to_dict(f: ExportFilter) -> dict:
    return {"types": f.types, "min_len": f.min_len, "max_len": f.max_len,
            "prefix": f.prefix, "regex": f.regex}


def filter_from_dict(d: dict | None) -> ExportFilter:
    d = d or {}
    return ExportFilter(types=d.get("types"), min_len=d.get("min_len"),
                        max_len=d.get("max_len"), prefix=d.get("prefix", ""),
                        regex=d.get("regex", ""))


class TemplateStore:
    """模板池。db_path 可注入（测试用 tmp 路径）。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else data_dir() / "templates.json"
        self._templates: dict[str, dict] = {}
        self._load()

    def _load(self):
        self.corrupt_backup: Path | None = None  # 损坏备份路径（MainWindow 提示用）
        if self.path.is_file():
            try:
                self._templates = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                logger.exception("模板池读取失败（文件损坏，已备份并回落内置预设）: %s",
                                 self.path)
                self.corrupt_backup = _backup_corrupt(self.path)
                self._templates = {}
        if not self._templates:
            self._templates = {n: dict(t) for n, t in BUILTIN_TEMPLATES.items()}
            try:
                self._save()
            except ValueError:
                pass  # 写入失败已在 _save 内记日志，内置预设可内存态继续使用

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._templates, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError as exc:
            logger.exception("模板池写入失败: %s", self.path)
            raise ValueError(f"模板池写入失败（{exc}）") from exc

    def names(self) -> list[str]:
        builtin = [n for n in BUILTIN_TEMPLATES if n in self._templates]
        return builtin + sorted(n for n in self._templates if n not in BUILTIN_TEMPLATES)

    def get(self, name: str) -> dict | None:
        return self._templates.get(name)

    def save(self, name: str, config: dict) -> None:
        if not name:
            raise ValueError("模板名称不能为空")
        self._templates[name] = config
        self._save()

    def rename(self, old: str, new: str) -> None:
        if old not in self._templates:
            raise ValueError(f"模板不存在: {old}")
        if not new or new in self._templates:
            raise ValueError(f"名称不可用: {new}")
        self._templates[new] = self._templates.pop(old)
        self._save()

    def delete(self, name: str) -> None:
        self._templates.pop(name, None)
        self._save()
