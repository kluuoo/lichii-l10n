"""Build the final translation queue with calibrated contexts.

Contexts come from context_scan's scope analysis; when that yields nothing useful
(empty, or a Qt type picked up from a mis-parsed call) the dominant context the
existing zh_CN.ts records for the same file is used instead. Anything still
unresolved is flagged for manual review.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import extract_cpp, extract_ui, parse_ts  # noqa: E402

ROOT = Path(r"C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125")
WORK = Path(__file__).parent
SCAN = ["src/yuzu", "src/qt_common", "src/frontend_common"]
SUSPICIOUS = {
    "", "QString", "QIcon", "std", "QCoreApplication", "ranges", "QObject", "Emulator",
    "QDialog", "QWidget", "QVariant", "QFile", "QPixmap", "QStringLiteral", "QMessageBox",
    "QInputDialog", "QDir", "Qt", "QDateTime", "QUrl", "QPushButton", "QLabel", "QLineEdit",
}


def norm(s: str) -> str:
    return " ".join(s.split())


def rel(p: str) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("/", "\\")
    except Exception:
        return p


def batch_of(rel_path: str) -> str:
    r = rel_path.replace("\\", "/")
    if "nup_dialogs" in r or "icon_search" in r or "icon_" in r:
        return "B3 NUP 转换与图标"
    if "compatibility_report" in r:
        return "B4 兼容性报告"
    if "shader_warm" in r:
        return "B5 着色器预热"
    if r.startswith("src/yuzu/updater"):
        return "B6 更新器"
    if "configure_microphone" in r:
        return "B7 麦克风设置"
    if "shared_translation" in r:
        return "B8 新增设置项标签/提示"
    if r.startswith("src/yuzu/main_window.cpp"):
        return "B2 主窗口与提示框"
    if r.endswith(".ui"):
        return "B1 界面文件（.ui）"
    return "B9 其他"


def main():
    ts = parse_ts(ROOT / "dist" / "languages" / "zh_CN.ts")
    ts_sources = {norm(e["source"]) for e in ts}
    file_ctx = {}
    for e in ts:
        f = e["file"].replace("\\", "/")
        if f:
            file_ctx.setdefault(f, Counter())[e["context"]] += 1

    harvested = []
    for d in SCAN:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.suffix in {".cpp", ".h", ".hpp", ".cc"}:
                harvested.extend(extract_cpp(p))
            elif p.suffix == ".ui":
                harvested.extend(extract_ui(p))

    rows = []
    seen = set()
    review = []
    for h in harvested:
        src = norm(h["source"])
        if src in ts_sources or src in seen:
            continue
        seen.add(src)
        relf = rel(h["file"])
        ts_key = "../../" + relf.replace("\\", "/")
        dominant = ""
        candidates = file_ctx.get(ts_key)
        if candidates:
            dominant = candidates.most_common(1)[0][0]
        ctx = h["context"]
        flagged = ctx in SUSPICIOUS
        if flagged and dominant:
            ctx = dominant
            flagged = False
        if not ctx:
            flagged = True
        row = {
            "batch": batch_of(relf),
            "file": relf,
            "line": h["line"],
            "context": ctx,
            "source": h["source"],
            "func": h["func"],
            "review": "yes" if flagged else "",
        }
        rows.append(row)
        if flagged:
            review.append(row)

    # manual context fixes for files the scope scan cannot resolve and that have no TS history
    overrides = {
        ("src\\yuzu\\shader_warm_dialog.cpp", 58): "ShaderWarmDialog",
        ("src\\yuzu\\shader_warm_dialog.cpp", 62): "ShaderWarmDialog",
        ("src\\qt_common\\game_list\\worker.cpp", 224): "GameListWorker",
        ("src\\yuzu\\main_window.cpp", 4585): "MainWindow",
        ("src\\yuzu\\main_window.cpp", 4633): "MainWindow",
        ("src\\yuzu\\main_window.cpp", 4637): "MainWindow",
        ("src\\yuzu\\nup_dialogs.cpp", 549): "NupEditDialog",
        ("src\\yuzu\\shader_warm_dialog.cpp", 41): "ShaderWarmDialog",
    }
    # not user-facing text: a context name used as a fake source and an fmt format template
    excluded_sources = {"ConfigureUI", "{} percentage (e.g. 50%)"}
    rows = [r for r in rows if r["source"] not in excluded_sources]
    for r in rows:
        fix = overrides.get((r["file"], int(r["line"])))
        if fix:
            r["context"] = fix
            r["review"] = ""

    rows.sort(key=lambda r: (r["batch"], r["file"], int(r["line"])))
    for i, r in enumerate(rows):
        r["idx"] = i

    with (WORK / "queue2.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f, fieldnames=["idx", "batch", "file", "line", "context", "source", "func", "review"]
        )
        w.writeheader()
        w.writerows(rows)

    with (WORK / "order.txt").open("w", encoding="utf-8") as f:
        for r in rows:
            src = r["source"].replace("\n", "\\n")
            f.write(f"{r['idx']:03d} | {r['context']} | {src}\n")

    print("total", len(rows))
    print("per batch", dict(Counter(r["batch"] for r in rows)))
    print("need review", len(review))
    for r in review:
        print(f"  {r['context'] or '<empty>':20s} {r['file']}:{r['line']}  {r['source'][:80]!r}")


if __name__ == "__main__":
    main()
