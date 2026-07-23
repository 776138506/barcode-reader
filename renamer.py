"""按码内容批量重命名的纯逻辑（不涉及 GUI）。

- 文件名模板复用 exporter 的占位符机制（{content}/{index}/{type} 等）
- 非法文件名字符 /\\:*?"<>| 替换为下划线
- 重名冲突自动追加 _2/_3…
- 一图多码取第一个码（由调用方在摘要中提示）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from exporter import ExportRecord, render_template

ILLEGAL_CHARS_RE = re.compile(r'[/\\:*?"<>|]')

DEFAULT_RENAME_TEMPLATE = "{content}"


def sanitize_filename(name: str) -> str:
    """替换非法文件名字符为下划线，并去掉首尾的点和空格（Windows 不允许）。"""
    cleaned = ILLEGAL_CHARS_RE.sub("_", name).strip().strip(".").strip()
    return cleaned or "unnamed"


@dataclass
class RenameItem:
    old_path: Path
    record: ExportRecord      # 第一个码
    extra_codes: int = 0      # 除第一个码外还有几个码（一图多码提示用）
    new_path: Path | None = None
    conflict_suffix: bool = False  # 因重名冲突追加了序号
    skipped: str = ""         # 非空表示跳过及原因


@dataclass
class RenamePlan:
    items: list[RenameItem] = field(default_factory=list)

    @property
    def actionable(self) -> list[RenameItem]:
        return [i for i in self.items if not i.skipped and i.new_path is not None]


def build_rename_plan(entries: list[tuple[str, list]], template: str,
                      skip_dir: Path | None = None) -> RenamePlan:
    """entries: [(图片路径, [DecodeResult, ...]), ...]（按当前列表顺序）。

    skip_dir 内的文件（如剪贴板临时目录）直接跳过。
    """
    plan = RenamePlan()
    used: set[Path] = set()
    for index, (path_str, results) in enumerate(entries, start=1):
        old = Path(path_str)
        item = RenameItem(old_path=old, record=None)  # type: ignore[arg-type]
        plan.items.append(item)
        if skip_dir is not None and old.is_relative_to(skip_dir):
            item.skipped = "粘贴的临时图片不支持重命名"
            continue
        if not results:
            item.skipped = "未识别到码"
            continue
        first = results[0]
        item.record = ExportRecord(filename=old.name, type=first.format,
                                   content=first.content)
        item.extra_codes = len(results) - 1
        base = sanitize_filename(render_template(template, item.record, index))
        candidate = old.with_name(base + old.suffix)
        n = 2
        while candidate in used or (candidate.exists() and candidate != old):
            item.conflict_suffix = True
            candidate = old.with_name(f"{base}_{n}{old.suffix}")
            n += 1
        used.add(candidate)
        item.new_path = candidate
    return plan


def execute_rename(plan: RenamePlan) -> tuple[int, list[tuple[Path, str]]]:
    """执行重命名，返回 (成功数, [(路径, 失败原因)])。失败单项跳过。"""
    ok = 0
    failures: list[tuple[Path, str]] = []
    for item in plan.actionable:
        try:
            item.old_path.rename(item.new_path)
            ok += 1
        except OSError as exc:
            failures.append((item.old_path, str(exc)))
    return ok, failures
