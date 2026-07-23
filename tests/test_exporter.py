"""模板渲染与导出测试。"""
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exporter import (DEFAULT_TEMPLATE, ExportRecord, export_csv, export_txt,  # noqa: E402
                      render_template, warn_unknown_placeholders)

NOW = datetime(2026, 7, 22, 9, 30, 15)

RECORDS = [
    ExportRecord(filename="a.png", type="QRCode", content="https://example.com/x"),
    ExportRecord(filename="b.png", type="Code128", content="ABC,123"),  # 含逗号，考验 CSV 转义
    ExportRecord(filename="c.png", type="DataMatrix", content="DM-42"),
]


def test_render_all_placeholders():
    out = render_template("{index}|{filename}|{type}|{content}|{date}|{time}",
                          RECORDS[0], 1, NOW)
    assert out == "1|a.png|QRCode|https://example.com/x|2026-07-22|09:30:15"


def test_render_unknown_placeholder_kept_and_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        unknown = warn_unknown_placeholders("{index}-{nope}-{content}")
    assert unknown == ["nope"]
    assert len(w) == 1 and issubclass(w[0].category, UserWarning)
    # 渲染不崩溃，未知占位符原样保留
    assert render_template("{index}-{nope}-{content}", RECORDS[0], 7, NOW) == "7-{nope}-https://example.com/x"


def test_export_txt(tmp_path):
    p = tmp_path / "out.txt"
    export_txt(RECORDS, str(p), DEFAULT_TEMPLATE)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0] == "1,a.png,QRCode,https://example.com/x"
    assert lines[1] == "2,b.png,Code128,ABC,123"  # TXT 不转义
    assert lines[2] == "3,c.png,DataMatrix,DM-42"


def test_export_csv_with_header(tmp_path):
    p = tmp_path / "out.csv"
    export_csv(RECORDS, str(p), DEFAULT_TEMPLATE, header="序号,文件名,码制,内容")
    raw = p.read_text(encoding="utf-8-sig").splitlines()
    assert raw[0] == "序号,文件名,码制,内容"
    assert raw[1] == "1,a.png,QRCode,https://example.com/x"
    assert raw[2] == '2,b.png,Code128,"ABC,123"'  # 逗号内容被正确加引号
    assert raw[3] == "3,c.png,DataMatrix,DM-42"


def test_export_csv_tab_template(tmp_path):
    p = tmp_path / "out_tab.csv"
    export_csv(RECORDS[:1], str(p), "{index}\t{type}\t{content}")
    raw = p.read_text(encoding="utf-8-sig").splitlines()
    assert raw == ["1\tQRCode\thttps://example.com/x"]
