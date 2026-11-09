"""Validate the Chinese translations and merge them into a new zh_CN.ts.

Validation:
  * every queue index is translated exactly once,
  * the %1/%2/%L1/%n placeholders match the source,
  * HTML tags match the source,
  * no empty translation.

Merge:
  * existing <message> entries get their <translation> replaced,
  * missing (context, source) pairs are added under the right <context>,
  * the unfinished entries and one whitespace-only translation are filled in,
  * indentation and the original XML declaration are preserved.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from extract import extract_cpp, extract_ui  # noqa: E402
from context_scan import code_only  # noqa: E402
from tr_a import T as T_A  # noqa: E402
from tr_b import T as T_B  # noqa: E402
from tr_c import T as T_C  # noqa: E402

ROOT = Path(r"C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125")
WORK = Path(__file__).parent
SCAN = ["src/yuzu", "src/qt_common", "src/frontend_common"]

PH = re.compile(r"%(?:\d+|L\d+|n|%)")
TAG = re.compile(r"</?[a-zA-Z][^>]*>")

# entries lupdate left unfinished or whitespace-only, keyed by normalised source
EXTRA = {
    "Flushes GPU buffer data back to guest memory before NCE invalidates the whole guest page, "
    "preserving it while the CPU store proceeds.":
        "在 NCE 使整个客户机页失效之前，将 GPU 缓冲区数据回写到客户机内存，"
        "使它在 CPU 存储过程中得以保留。",
    "Applies NCE code patches to runtime-loaded NRO modules.This is required for some games to "
    "run correctly.":
        "对运行时加载的 NRO 模块应用 NCE 代码补丁。部分游戏需要此设置才能正常运行。",
    "Controls the GPU fence synchronization behavior.\nImmediate is the fastest option, but can "
    "introduce some issues.\nBalanced offers better compatibility and may fix issues in some "
    "games.\nAccurate further improves compatibility at the cost of some performance.\nDefault "
    "follows the GPU Mode setting.":
        "控制 GPU 栅栏同步行为。\n“立即”速度最快，但可能引入一些问题。\n"
        "“均衡”兼容性更好，可能修复部分游戏的问题。\n"
        "“精确”以部分性能为代价进一步提升兼容性。\n“默认”跟随 GPU 模式设置。",
    "Failed to announce the room to the public lobby. In order to host a room publicly, you must "
    "have a valid Eden account configured in Emulation -> Configure -> Web. If you do not want to "
    "publish a room in the public lobby, then select Unlisted instead.\nDebug Message: ":
        "无法将房间公布到公共大厅。要公开托管房间，必须在“模拟 → 配置 → 网页”中配置有效的 "
        "Eden 账号。如果你不想在公共大厅公开房间，请改为选择“不公开”。\n调试信息：",
    "GPU Readback Before NCE Invalidation": "NCE 失效前的 GPU 回读",
    "Patch Runtime NROs for NCE": "为 NCE 修补运行时 NRO",
}


def norm(s: str) -> str:
    return " ".join(s.split())


# the migration dialog stores its labels with QT_TR_NOOP but translates them with QObject::tr
CONTEXT_ALIAS = {"Emulator": "QObject"}


FIXUPS_SOURCE = norm(
    "Please select the how you would like the RomFS dumped.<br>Full will copy all of the files "
    "into the new directory while <br>skeleton will only create the directory structure."
)
FIXUPS_TEXT = (
    "请选择希望如何导出 RomFS。<br>“完整”会把所有文件复制到新目录中，"
    "<br>“结构”只创建目录结构。"
)


def add_message(ctx, src: str, text: str) -> None:
    if len(ctx):
        last = ctx[-1]
        if not (last.tail or "").strip():
            last.tail = "\n    "
    msg = etree.SubElement(ctx, "message")
    msg.text = "\n        "
    s = etree.SubElement(msg, "source")
    s.text = src
    s.tail = "\n        "
    t = etree.SubElement(msg, "translation")
    t.text = text
    t.tail = "\n    "
    msg.tail = "\n"


def set_translation(msg, text: str) -> None:
    tr = msg.find("translation")
    if tr is None:
        tr = etree.SubElement(msg, "translation")
    tr.text = text
    if tr.get("type"):
        del tr.attrib["type"]
    for child in list(tr):
        tr.remove(child)


def main():
    trans = {}
    for src in (T_A, T_B, T_C):
        for k, v in src.items():
            if k in trans:
                raise SystemExit(f"duplicate index {k}")
            trans[k] = v

    rows = list(csv.DictReader((WORK / "queue2.csv").open(encoding="utf-8-sig")))
    by_idx = {int(r["idx"]): r for r in rows}

    errors = []
    missing_idx = [i for i in by_idx if i not in trans]
    extra_idx = [i for i in trans if i not in by_idx]
    if missing_idx:
        errors.append(f"missing translations for indices: {missing_idx}")
    if extra_idx:
        errors.append(f"translations for unknown indices: {extra_idx}")

    for i, r in by_idx.items():
        t = trans.get(i, "")
        if not t.strip():
            errors.append(f"[{i}] empty translation: {r['source'][:60]!r}")
            continue
        a = sorted(PH.findall(r["source"]))
        b = sorted(PH.findall(t))
        if a != b:
            errors.append(f"[{i}] placeholder mismatch {a} -> {b}: {r['source'][:70]!r}")
        sa = sorted(TAG.findall(r["source"]))
        sb = sorted(TAG.findall(t))
        if sa != sb:
            errors.append(f"[{i}] tag mismatch {sa} -> {sb}: {r['source'][:60]!r}")
    for src, text in EXTRA.items():
        if sorted(PH.findall(src)) != sorted(PH.findall(text)):
            errors.append(f"placeholder mismatch in EXTRA: {src[:50]!r}")

    if errors:
        print("VALIDATION FAILED")
        for e in errors[:40]:
            print(" ", e)
        raise SystemExit(1)
    print(f"translations OK: {len(trans)} of {len(by_idx)} rows")

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
    by_source = {}
    for h in harvested:
        by_source.setdefault(norm(h["source"]), set()).add(h["context"])

    # only trust contexts that really exist as a type/namespace or are already used by the file
    declared = set()
    ns_re = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)[^;{]*\{")
    space_re = re.compile(r"\bnamespace\s+([A-Za-z_]\w*)\s*(?:final\s*)?\{")
    for d in SCAN:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.suffix in {".cpp", ".h", ".hpp", ".cc"}:
                code = code_only(p.read_text(encoding="utf-8", errors="replace"))
                declared |= set(ns_re.findall(code)) | set(space_re.findall(code))

    original_ctx = set()
    for ctx in etree.parse(str(ROOT / "dist" / "languages" / "zh_CN.ts")).getroot().findall("context"):
        original_ctx.add(ctx.findtext("name"))

    tree = etree.parse(str(ROOT / "dist" / "languages" / "zh_CN.ts"))
    root = tree.getroot()
    contexts = {c.findtext("name"): c for c in root.findall("context")}

    def find_message(ctx_name: str, source: str):
        ctx = contexts.get(ctx_name)
        if ctx is None:
            return None
        for msg in ctx.findall("message"):
            if msg.findtext("source") == source:
                return msg
        return None

    added = updated = 0
    for i, r in by_idx.items():
        text = trans[i]
        src = r["source"]
        ctxs = by_source.get(norm(src)) or {r["context"]}
        ctxs = {CONTEXT_ALIAS.get(c, c) for c in ctxs}
        ctxs = {c for c in ctxs if c in declared or c in original_ctx} or {r["context"]}
        for cname in sorted(ctxs):
            cname = cname or r["context"]
            ctx = contexts.get(cname)
            if ctx is None:
                if len(root):
                    last = root[-1]
                    if not (last.tail or "").strip():
                        last.tail = "\n"
                ctx = etree.SubElement(root, "context")
                ctx.text = "\n    "
                ctx.tail = "\n"
                etree.SubElement(ctx, "name").text = cname
                ctx[-1].tail = "\n    "
                contexts[cname] = ctx
            msg = find_message(cname, src)
            if msg is None:
                add_message(ctx, src, text)
                added += 1
            else:
                set_translation(msg, text)
                updated += 1

    extra_done = 0
    extra_n = {norm(k): v for k, v in EXTRA.items()}
    for msg in root.iter("message"):
        src = norm(msg.findtext("source") or "")
        if src in extra_n:
            tr = msg.find("translation")
            empty = tr is None or not (tr.text or "").strip()
            unfinished = tr is not None and tr.get("type") in ("unfinished", "vanished")
            if empty or unfinished:
                set_translation(msg, extra_n[src])
                extra_done += 1

    # fix a pre-existing translation whose closing tags were malformed
    for msg in root.iter("message"):
        if norm(msg.findtext("source") or "") == FIXUPS_SOURCE:
            set_translation(msg, FIXUPS_TEXT)
            break

    out = WORK / "zh_CN.ts"
    tree.write(str(out), xml_declaration=True, encoding="utf-8", pretty_print=False)
    raw = out.read_text(encoding="utf-8")
    raw = raw.replace("<?xml version='1.0' encoding='UTF-8'?>", '<?xml version="1.0" ?>', 1)
    raw = raw.replace("<?xml version='1.0' encoding='utf-8'?>", '<?xml version="1.0" ?>', 1)
    out.write_text(raw, encoding="utf-8")

    print(f"wrote {out}: added {added}, updated {updated}, filled {extra_done}")


if __name__ == "__main__":
    main()
