"""历史记录库（SQLite）：解码结果自动落库，支持关键词搜索与时间排序。

数据库文件放平台惯例数据目录（见 paths.data_dir）。
所有写入/查询失败由调用方兜底（不得影响主流程），本模块内部也防御性处理。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,           -- ISO 时间戳（本地时间）
    filename TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_ts ON records(ts DESC);
CREATE INDEX IF NOT EXISTS idx_records_content ON records(content);

CREATE TABLE IF NOT EXISTS strategy_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                -- ISO 时间戳（本地时间）
    image_sha256 TEXT NOT NULL,      -- 源文件内容哈希
    features TEXT NOT NULL,          -- JSON：图像特征（亮度/对比度/模糊度/尺寸等）
    attempts TEXT NOT NULL,          -- JSON 数组：每层参数组合 + hit + 耗时 ms
    final_strategy TEXT NOT NULL,    -- 命中策略（未命中为空串）
    final_hit_count INTEGER NOT NULL -- 最终码数量（0 = 未识别）
);
CREATE INDEX IF NOT EXISTS idx_strategy_ts ON strategy_log(ts DESC);
"""


@dataclass
class HistoryRecord:
    ts: str
    filename: str
    type: str
    content: str
    source_path: str


class History:
    """SQLite 历史库。db_path 可注入（测试用 tmp 路径）。"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def add(self, filename: str, type_: str, content: str,
            source_path: str, ts: datetime | None = None) -> None:
        """写入一条历史记录。"""
        ts = ts or datetime.now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO records (ts, filename, type, content, source_path)"
                " VALUES (?, ?, ?, ?, ?)",
                (ts.isoformat(timespec="seconds"), filename, type_, content, source_path),
            )

    def add_batch(self, records: list[HistoryRecord]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO records (ts, filename, type, content, source_path)"
                " VALUES (?, ?, ?, ?, ?)",
                [(r.ts, r.filename, r.type, r.content, r.source_path) for r in records],
            )

    def search(self, keyword: str = "", limit: int = 500) -> list[HistoryRecord]:
        """按内容关键词搜索（空串=全部），按时间倒序。"""
        with self._connect() as conn:
            if keyword:
                rows = conn.execute(
                    "SELECT ts, filename, type, content, source_path FROM records"
                    " WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",
                    (f"%{keyword}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ts, filename, type, content, source_path FROM records"
                    " ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [HistoryRecord(*row) for row in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def add_strategy_log(self, image_sha256: str, features: dict,
                         attempts: list[dict], final_strategy: str,
                         final_hit_count: int, ts: datetime | None = None) -> None:
        """写入一条识别管线策略日志（features/attempts 序列化为 JSON）。"""
        ts = ts or datetime.now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO strategy_log"
                " (ts, image_sha256, features, attempts, final_strategy, final_hit_count)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (ts.isoformat(timespec="seconds"), image_sha256,
                 json.dumps(features, ensure_ascii=False),
                 json.dumps(attempts, ensure_ascii=False),
                 final_strategy, final_hit_count),
            )

    def strategy_logs(self, limit: int = 100) -> list[dict]:
        """按时间倒序读取策略日志（JSON 字段已解析）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ts, image_sha256, features, attempts, final_strategy,"
                " final_hit_count FROM strategy_log ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"ts": ts, "image_sha256": sha,
             "features": json.loads(features), "attempts": json.loads(attempts),
             "final_strategy": final_strategy, "final_hit_count": hit_count}
            for ts, sha, features, attempts, final_strategy, hit_count in rows
        ]
