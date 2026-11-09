"""Verify the merged zh_CN.ts: coverage, placeholders, tags, formatting."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from extract import extract_cpp, extract_ui  # noqa: E402

ROOT = Path(r"C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125")
WORK = Path(__file__).parent
SCAN = ["src/yuzu", "src/qt_common", "src/frontend_common"]
NEW = WORK / "zh_CN.ts"

PH = re.compile(r"%(?:\d+|L\d+|n|%)")
TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def norm(s: str) -> str:
    return " ".join(s.split())


def main():
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

    root = etree.parse(str(NEW)).getroot()
    entries = []
    for ctx in root.findall("context"):
        name = ctx.findtext("name")
        for m in ctx.findall("message"):
            tr = m.find("translation")
            txt = (tr.text or "") if tr is not None else ""
            if tr is not None and not tr.text:
                txt = "".join(n.text or "" for n in tr.findall("numerusform"))
            entries.append((name, m.findtext("source") or "", txt, tr.get("type") if tr is not None else None))

    have = {(c, s) for c, s, _t, _f in entries}
    have_src = {norm(s) for _c, s, _t, _f in entries}

    missing = []
    seen = set()
    for h in harvested:
        key = norm(h["source"])
        if key in have_src and (h["context"], h["source"]) in have:
            continue
        if key in have_src:
            # present under another context; acceptable unless this exact context matters
            continue
        if key in seen:
            continue
        seen.add(key)
        missing.append(h)

    badge = [e for e in entries if e[3]]
    empty = [e for e in entries if not e[2].strip() and e[1].strip()]

    ph_bad = []
    tag_bad = []
    for c, s, t, _f in entries:
        if not t.strip():
            continue
        if sorted(PH.findall(s)) != sorted(PH.findall(t)):
            ph_bad.append((c, s, t))
        if sorted(TAG.findall(s)) != sorted(TAG.findall(t)):
            tag_bad.append((c, s, t))

    print(f"messages: {len(entries)}")
    print(f"unfinished/vanished: {len(badge)}")
    print(f"empty (non-blank source): {len(empty)}")
    print(f"harvested unique sources: {len({norm(h['source']) for h in harvested})}")
    print(f"missing (not anywhere in ts): {len(missing)}")
    for m in missing[:15]:
        print("   MISS", m["context"], "|", repr(m["source"][:70]))
    print(f"placeholder mismatches: {len(ph_bad)}")
    for c, s, t in ph_bad[:10]:
        print("   PH", c, "|", repr(s[:50]), "->", repr(t[:50]))
    print(f"tag mismatches: {len(tag_bad)}")
    for c, s, t in tag_bad[:10]:
        print("   TAG", c, "|", repr(s[:40]), "->", repr(t[:40]))


if __name__ == "__main__":
    main()
