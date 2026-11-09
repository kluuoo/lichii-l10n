"""List queue rows whose context is neither a declared type nor an existing TS context."""
import csv
import re
import sys
from pathlib import Path
from lxml import etree

ROOT = Path(r"C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125")
WORK = Path(__file__).parent
SCAN = ["src/yuzu", "src/qt_common", "src/frontend_common"]

DECL = re.compile(r"\b(?:class|struct|namespace)\s+([A-Za-z_]\w*)")

names = set()
for d in SCAN:
    base = ROOT / d
    if not base.exists():
        continue
    for p in base.rglob("*"):
        if p.suffix in {".cpp", ".h", ".hpp", ".cc"}:
            names |= set(DECL.findall(p.read_text(encoding="utf-8", errors="replace")))

ts = etree.parse(str(ROOT / "dist" / "languages" / "zh_CN.ts")).getroot()
ts_ctx = {c.findtext("name") for c in ts.findall("context")}

rows = list(csv.DictReader((WORK / "queue2.csv").open(encoding="utf-8-sig")))
bad = [r for r in rows if r["context"] not in names and r["context"] not in ts_ctx]
print("declared names:", len(names), "ts contexts:", len(ts_ctx))
print("suspect rows:", len(bad))
for r in bad:
    print(f"{r['idx']:>3} {r['context']:<22} {r['file']}:{r['line']}  {r['source'][:60]!r}")
