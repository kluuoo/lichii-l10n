"""Categorise the untranslated zh_CN strings into translation batches.

Reads missing.csv from extract.py plus zh_CN.ts, then:
  * carries translations over from entries whose only change is Eden -> Lichii,
  * groups the rest by UI area,
  * writes queue.csv (batch, file, source, carried translation) and stats.json.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import parse_ts  # noqa: E402

ROOT = Path(r"C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125")
WORK = Path(__file__).parent

BRAND = [
    ("Lichii", "Eden"),
    ("lichii", "eden"),
    ("LICHII", "EDEN"),
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def debrand(s: str) -> str:
    out = s
    for new, old in BRAND:
        out = out.replace(new, old)
    return out


def batch_of(rel: str) -> str:
    rel = rel.replace("\\", "/")
    if rel.startswith("src/yuzu/nup_dialogs.cpp") or "icon_search" in rel:
        return "B3 NUP 转换与图标"
    if "compatibility_report" in rel:
        return "B4 兼容性报告"
    if "shader_warm" in rel:
        return "B5 着色器预热"
    if rel.startswith("src/yuzu/updater"):
        return "B6 更新器"
    if "configure_microphone" in rel:
        return "B7 麦克风设置"
    if "shared_translation" in rel:
        return "B8 新增设置项标签/提示"
    if rel.startswith("src/yuzu/main_window.cpp"):
        return "B2 主窗口与提示框"
    if rel.endswith(".ui"):
        return "B1 界面文件（.ui）"
    return "B9 其他"


def main():
    ts = parse_ts(ROOT / "dist" / "languages" / "zh_CN.ts")
    ts_norm = {}
    for e in ts:
        ts_norm.setdefault(norm(e["source"]), e)

    rows = list(csv.DictReader((WORK / "missing.csv").open(encoding="utf-8-sig")))
    queue = []
    stats = Counter()
    for r in rows:
        src = norm(r["source"])
        carried = ""
        match_kind = "new"
        for cand, entry in ts_norm.items():
            if norm(debrand(cand)) == src:
                carried = entry["translation"]
                match_kind = "rebrand"
                break
        if not carried:
            # also try the reverse direction (source is old Eden wording, ts has Lichii)
            for cand, entry in ts_norm.items():
                if norm(debrand(src)) == norm(cand):
                    carried = entry["translation"]
                    match_kind = "rebrand"
                    break
        stats[match_kind] += 1
        queue.append(
            {
                "batch": batch_of(r["file"]),
                "file": r["file"],
                "line": r["line"],
                "context": r["context"],
                "source": r["source"],
                "suggested": carried,
                "kind": match_kind,
            }
        )

    queue.sort(key=lambda q: (q["batch"], q["file"], int(q["line"])))
    with (WORK / "queue.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f, fieldnames=["batch", "file", "line", "context", "source", "suggested", "kind"]
        )
        w.writeheader()
        w.writerows(queue)

    per_batch = Counter(q["batch"] for q in queue)
    res = {
        "total": len(queue),
        "rebrand": stats["rebrand"],
        "new": stats["new"],
        "per_batch": dict(sorted(per_batch.items())),
    }
    (WORK / "stats.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
