"""Lichii Qt UI string extractor / zh_CN.ts coverage audit.

Approximates `lupdate` for planning purposes: lexes C++ sources for tr()/translate()
calls and harvests translatable <string> elements from .ui files, then compares the
harvest against dist/languages/zh_CN.ts.

Usage:
    python extract.py <project-root> <out-dir>
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from context_scan import context_at, lambda_context, scopes  # noqa: E402

SCAN_DIRS = [
    "src/yuzu",
    "src/qt_common",
    "src/frontend_common",
]
CPP_EXTS = {".cpp", ".h", ".hpp", ".cc"}
UI_EXTS = {".ui"}

TRANSLATE_CALL = re.compile(r"(?<![\w.])(tr|QT_TR_NOOP|QT_TRANSLATE_NOOP|translate|qtTrId)\s*\(")
CLASS_QUALIFIER = re.compile(r"\b([A-Za-z_]\w*)::([~A-Za-z_]\w*)\s*\(")


def lex_cpp(text: str):
    """Yield (kind, value, pos) tokens; kind in code/string/char/comment."""
    i, n = 0, len(text)
    buf = []
    buf_start = 0

    def flush(end):
        if buf:
            yield ("code", "".join(buf), buf_start)
            buf.clear()

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            if buf:
                yield ("code", "".join(buf), buf_start)
                buf.clear()
            j = text.find("\n", i)
            j = n if j < 0 else j
            yield ("comment", text[i:j], i)
            i = j
            continue
        if c == "/" and nxt == "*":
            if buf:
                yield ("code", "".join(buf), buf_start)
                buf.clear()
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            yield ("comment", text[i:j], i)
            i = j
            continue
        if c == '"' or (c == "R" and nxt == '"'):
            if buf:
                yield ("code", "".join(buf), buf_start)
                buf.clear()
            start = i
            if c == "R":  # raw string
                m = re.match(r'R"([^(]{0,16})\(', text[i:])
                delim = m.group(1) if m else ""
                end_tok = ")" + delim + '"'
                j = text.find(end_tok, i + len(m.group(0)) if m else i + 2)
                j = n if j < 0 else j + len(end_tok)
                yield ("string", text[start:j], start)
                i = j
                continue
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            yield ("string", text[start:j], start)
            i = j
            continue
        if c == "'":
            if buf:
                yield ("code", "".join(buf), buf_start)
                buf.clear()
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "'":
                    j += 1
                    break
                j += 1
            yield ("char", text[i:j], i)
            i = j
            continue
        if not buf:
            buf_start = i
        buf.append(c)
        i += 1
    if buf:
        yield ("code", "".join(buf), buf_start)


def unescape_literal(tok: str) -> str:
    """Best-effort C++ string literal -> text."""
    body = tok
    if body.startswith('R"'):
        m = re.match(r'R"([^(]{0,16})\((.*)\)\1"$', body, re.S)
        return m.group(2) if m else body
    body = body[1:-1]
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < len(body) else ""
        mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0"}
        if nxt in mapping:
            out.append(mapping[nxt])
            i += 2
        elif nxt == "x":
            m = re.match(r"x([0-9A-Fa-f]+)", body[i + 1:])
            if m:
                out.append(chr(int(m.group(1), 16)))
                i += 1 + len(m.group(0))
            else:
                out.append(nxt)
                i += 2
        elif nxt == "u":
            m = re.match(r"u([0-9A-Fa-f]{4})", body[i + 1:])
            if m:
                out.append(chr(int(m.group(1), 16)))
                i += 1 + len(m.group(0))
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(nxt)
            i += 2
    return "".join(out)


def enclosing_class(prefix: str) -> str:
    last = None
    for m in CLASS_QUALIFIER.finditer(prefix):
        last = m.group(1)
    return last or ""


def extract_cpp(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    toks = list(lex_cpp(text))
    file_scopes = scopes(text)
    lam_ctx = lambda_context(text)
    results = []
    for idx, (kind, value, pos) in enumerate(toks):
        if kind != "code":
            continue
        for m in TRANSLATE_CALL.finditer(value):
            func = m.group(1)
            # gather the call arguments as literal groups; adjacent literals concatenate
            args = []
            cur = None
            sep = "start"
            for kind2, val2, _p2 in toks[idx + 1:]:
                if kind2 == "comment":
                    continue
                if kind2 == "string":
                    part = unescape_literal(val2)
                    if cur is None or sep == "comma":
                        cur = [part]
                        args.append(cur)
                    else:
                        cur.append(part)
                    sep = "string"
                    continue
                if kind2 == "code":
                    stripped = val2.strip()
                    if not stripped:
                        if sep == "string":
                            sep = "ws"
                        continue
                    if stripped.startswith(",") and sep in ("string", "ws"):
                        sep = "comma"
                        continue
                    break
                break
            strings = ["".join(a) for a in args]
            if not strings:
                continue
            if func in ("translate", "QT_TRANSLATE_NOOP"):
                if len(strings) < 2:
                    continue
                ctx, src = strings[0], strings[1]
                disamb = ""
            else:
                src = strings[0]
                disamb = strings[1] if len(strings) > 1 else ""
                ctx = context_at(file_scopes, pos + m.start()) or lam_ctx
                if lam_ctx and ctx in ("", None):
                    ctx = lam_ctx
                if not ctx:
                    ctx = enclosing_class(text[max(0, pos - 4000):pos])
            results.append(
                {
                    "file": str(path),
                    "line": text.count("\n", 0, pos) + 1,
                    "context": ctx,
                    "source": src,
                    "comment": disamb,
                    "func": func,
                }
            )
    return results


def extract_ui(path: Path):
    try:
        tree = etree.parse(str(path))
    except Exception:
        return []
    root = tree.getroot()
    cls = root.findtext("class") or ""
    results = []
    for el in root.iter("string"):
        if el.get("untranslatable") == "false" and (el.get("notr") == "true"):
            continue
        if el.get("notr") == "true":
            continue
        txt = "".join(el.itertext())
        if not txt.strip():
            continue
        results.append(
            {
                "file": str(path),
                "line": el.sourceline or 0,
                "context": cls,
                "source": txt,
                "comment": "",
                "func": "ui",
            }
        )
    return results


def parse_ts(ts_path: Path):
    tree = etree.parse(str(ts_path))
    root = tree.getroot()
    entries = []
    for ctx in root.iter("context"):
        name = ctx.findtext("name") or ""
        for msg in ctx.iter("message"):
            src = msg.findtext("source")
            if src is None:
                continue
            tr = msg.find("translation")
            tr_text = "".join(tr.itertext()) if tr is not None else ""
            flags = tr.get("type") if tr is not None else None
            loc = msg.find("location")
            entries.append(
                {
                    "context": name,
                    "source": src,
                    "translation": tr_text,
                    "flag": flags,
                    "file": loc.get("filename") if loc is not None else "",
                }
            )
    return entries


def main():
    root = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)

    harvested = []
    scanned = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.suffix in CPP_EXTS:
                scanned.append(str(p))
                harvested.extend(extract_cpp(p))
            elif p.suffix in UI_EXTS:
                scanned.append(str(p))
                harvested.extend(extract_ui(p))

    ts = parse_ts(root / "dist" / "languages" / "zh_CN.ts")
    by_src = {}
    by_ctx_src = {}
    for e in ts:
        by_src.setdefault(e["source"], []).append(e)
        by_ctx_src[(e["context"], e["source"])] = e

    # normalize whitespace-insensitive source compare
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip())

    norm_map = {}
    for e in ts:
        norm_map.setdefault(norm(e["source"]), e)

    seen = set()
    missing = []
    for h in harvested:
        key = (h["context"], h["source"])
        if key in by_ctx_src:
            continue
        if norm(h["source"]) in norm_map:
            continue
        nk = norm(h["source"])
        if nk in seen:
            continue
        seen.add(nk)
        missing.append(h)

    # entries present in TS but no longer harvested
    harvested_norm = {norm(h["source"]) for h in harvested}
    stale = [e for e in ts if norm(e["source"]) not in harvested_norm]

    unfinished = [e for e in ts if e["flag"] == "unfinished"]
    van = [e for e in ts if e["flag"] == "vanished"]
    same = [e for e in ts if e["translation"] and e["translation"].strip() == e["source"].strip()]

    def rel(p):
        try:
            return str(Path(p).resolve().relative_to(root))
        except Exception:
            return p

    per_file = {}
    for m in missing:
        per_file.setdefault(rel(m["file"]), []).append(m)

    summary = {
        "scanned_files": len(scanned),
        "harvested_calls": len(harvested),
        "harvested_unique_sources": len({norm(h["source"]) for h in harvested}),
        "ts_messages": len(ts),
        "ts_unfinished": len(unfinished),
        "ts_vanished": len(van),
        "ts_translation_equals_source": len(same),
        "missing_unique": len(missing),
        "missing_per_file": {k: len(v) for k, v in sorted(per_file.items(), key=lambda kv: -len(kv[1]))},
        "stale_entries": len(stale),
    }

    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    with (out / "missing.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["file", "line", "context", "source", "func"])
        for m in sorted(missing, key=lambda x: (x["file"], x["line"])):
            w.writerow([rel(m["file"]), m["line"], m["context"], m["source"], m["func"]])

    with (out / "unfinished.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["context", "file", "source", "translation"])
        for e in unfinished:
            w.writerow([e["context"], e["file"], e["source"], e["translation"]])

    with (out / "stale.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["context", "file", "source", "translation", "flag"])
        for e in stale:
            w.writerow([e["context"], e["file"], e["source"], e["translation"], e["flag"]])

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
