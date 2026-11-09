"""End-to-end re-check of the localisation work and the applied source edits.

Runs offline (no Qt, no compiler) and prints PASS/FAIL lines:

  1. zh_CN.ts decodes as strict UTF-8 and parses as TS 2.1 with language zh_CN
  2. every translation is non-empty (numerus handled), no unfinished/vanished left
  3. placeholders (%1..%9, %L1, %n, %%) and HTML tags match the source
  4. every string the C++/UI sources ask for exists in the .ts
  5. every message added without <location> sits in a context that is a real
     class/struct/namespace of the source tree
  6. the four source edits are present and structurally sane
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from extract import extract_cpp, extract_ui  # noqa: E402
from context_scan import code_only  # noqa: E402

ROOT = Path(r"C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125")
WORK = Path(__file__).parent
SCAN = ["src/yuzu", "src/qt_common", "src/frontend_common"]
TS = ROOT / "dist" / "languages" / "zh_CN.ts"

PH = re.compile(r"%(?:\d+|L\d+|n|%)")
TAG = re.compile(r"</?[a-zA-Z][^>]*>")
DECL_CLASS = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)[^;{]*\{")
DECL_NS = re.compile(r"\bnamespace\s+([A-Za-z_]\w*)\s*(?:final\s*)?\{")

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def norm(s: str) -> str:
    return " ".join(s.split())


def main() -> int:
    # 1. decode + parse
    raw = TS.read_bytes()
    try:
        text = raw.decode("utf-8")
        utf8_ok = True
    except UnicodeDecodeError as exc:
        text, utf8_ok = "", False
        print("  utf-8 error:", exc)
    check("zh_CN.ts is valid UTF-8", utf8_ok, f"{len(raw):,} bytes")

    tree = etree.parse(str(TS))
    root = tree.getroot()
    check(
        "TS root is version 2.1 / language zh_CN",
        root.tag == "TS" and root.get("language") == "zh_CN" and root.get("version") == "2.1",
        f"language={root.get('language')} version={root.get('version')}",
    )

    contexts = root.findall("context")
    entries = []
    for ctx in contexts:
        name = ctx.findtext("name") or ""
        for msg in ctx.findall("message"):
            tr = msg.find("translation")
            if tr is None:
                txt, forms, flag = "", [], None
            else:
                txt = tr.text or ""
                forms = [n.text or "" for n in tr.findall("numerusform")]
                flag = tr.get("type")
            entries.append(
                {
                    "context": name,
                    "source": msg.findtext("source") or "",
                    "translation": txt,
                    "forms": forms,
                    "flag": flag,
                    "has_location": msg.find("location") is not None,
                }
            )

    # 2. completeness
    bad_flags = [e for e in entries if e["flag"]]
    check("no unfinished / vanished entries", not bad_flags, f"{len(bad_flags)} left")
    empty = [
        e for e in entries
        if not e["translation"].strip()
        and not any(f.strip() for f in e["forms"])
        and e["source"].strip()
    ]
    check("no empty translations", not empty, f"{len(empty)} empty: "
          + ", ".join(repr(e["source"][:30]) for e in empty[:3]))

    # 3. placeholders + tags
    ph_bad = [
        e for e in entries
        if (e["translation"].strip() or any(f.strip() for f in e["forms"]))
        and sorted(PH.findall(e["source"])) != sorted(PH.findall(e["translation"] or "".join(e["forms"])))
    ]
    check("placeholders match everywhere", not ph_bad,
          f"{len(ph_bad)} mismatches" + (f", first: {ph_bad[0]['source'][:40]!r}" if ph_bad else ""))
    tag_bad = [
        e for e in entries
        if (e["translation"].strip() or any(f.strip() for f in e["forms"]))
        and sorted(TAG.findall(e["source"])) != sorted(TAG.findall(e["translation"] or "".join(e["forms"])))
    ]
    check("HTML tags match everywhere", not tag_bad,
          f"{len(tag_bad)} mismatches" + (f", first: {tag_bad[0]['source'][:40]!r}" if tag_bad else ""))

    # 4. coverage against the sources
    harvested = []
    files = 0
    for d in SCAN:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.suffix in {".cpp", ".h", ".hpp", ".cc"}:
                files += 1
                harvested.extend(extract_cpp(p))
            elif p.suffix == ".ui":
                files += 1
                harvested.extend(extract_ui(p))

    sources = {norm(e["source"]) for e in entries}
    missing, seen = [], set()
    for h in harvested:
        key = norm(h["source"])
        if key in sources or key in seen:
            continue
        seen.add(key)
        missing.append(h)
    allowed_missing = {"ConfigureUI", "{} percentage (e.g. 50%)"}
    real_missing = [m for m in missing if norm(m["source"]) not in allowed_missing]
    check(
        "every UI string has a translation",
        not real_missing,
        f"{len({norm(m['source']) for m in harvested})} unique strings from {files} files, "
        f"{len(real_missing)} missing",
    )

    # 5. contexts of the added entries are real types or explicit translate() contexts
    declared = set()
    for d in SCAN:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.suffix in {".cpp", ".h", ".hpp", ".cc"}:
                code = code_only(p.read_text(encoding="utf-8", errors="replace"))
                declared |= set(DECL_CLASS.findall(code)) | set(DECL_NS.findall(code))

    # QT_TRANSLATE_NOOP("Hotkeys", ...) / QCoreApplication::translate("Ctx", ...) name their context
    # explicitly, and QObject::tr(...) (used by migration_worker) resolves to QObject.
    explicit = {h["context"] for h in harvested if h["func"] in ("translate", "QT_TRANSLATE_NOOP")}
    explicit.add("QObject")
    valid_contexts = declared | explicit

    added = [e for e in entries if not e["has_location"]]
    bogus = sorted({e["context"] for e in added if e["context"] not in valid_contexts})
    check("added entries use real class/namespace contexts", not bogus,
          f"{len(added)} added entries, {len({e['context'] for e in added})} contexts"
          + (f", bogus: {bogus}" if bogus else ""))

    # 7. structural extras
    pairs = [(e["context"], e["source"]) for e in entries]
    dups = {p for p in pairs if pairs.count(p) > 1}
    check("no duplicate (context, source) pairs", not dups, f"{len(dups)} duplicates")

    new_dialog_contexts = {
        "NupEditDialog", "NupMetadataDialog", "NupProgressDialog", "IconDropZone",
        "IconSearch", "Dialog", "ShaderWarmDialog", "ConfigureMicrophone", "GameListWorker",
    }
    present = {c.findtext("name") for c in contexts}
    check("new dialog contexts present", new_dialog_contexts <= present,
          f"missing: {sorted(new_dialog_contexts - present)}")

    spot = {
        "About Lichii": "关于 Lichii",
        "Precache Shaders": "预缓存着色器",
        "Submit compatibility report": "提交兼容性报告",
        "Microphone volume:": "麦克风音量：",
        "Exit Lichii": "退出 Lichii",
    }
    tr_map = {(e["context"], e["source"]): e["translation"] for e in entries}
    spot_bad = [k for k, v in spot.items() if (k, v) not in {(s, t) for (_c, s), t in tr_map.items()}]
    check("spot-check of key strings", not spot_bad, f"wrong: {spot_bad}")

    ctrl = [e for e in entries if any(ord(ch) < 32 and ch not in "\n\t" for ch in (e["translation"] or ""))]
    check("no stray control characters in translations", not ctrl, f"{len(ctrl)} entries")

    # 6. the applied source edits
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    check(
        "CMakeLists: ENABLE_QT_TRANSLATION defaults to ON",
        'option(ENABLE_QT_TRANSLATION "Enable translations for the Qt frontend" ON)' in cmake,
    )

    ui = (ROOT / "src/yuzu/configuration/configure_ui.cpp").read_text(encoding="utf-8")
    check(
        "configure_ui: native language table + lookup wired in",
        "constexpr std::array native_language_names" in ui
        and "QString NativeLanguageName(const QString& locale)" in ui
        and "const QString native = NativeLanguageName(locale);" in ui
        and ui.count('std::make_pair("zh_CN", "简体中文")') == 1,
    )
    ui_code = code_only(ui)
    check(
        "configure_ui: balanced braces/parens",
        ui_code.count("{") == ui_code.count("}") and ui_code.count("(") == ui_code.count(")"),
        f"braces {ui_code.count('{')}/{ui_code.count('}')}, parens {ui_code.count('(')}/{ui_code.count(')')}",
    )

    hdr = (ROOT / "src/yuzu/main_window.h").read_text(encoding="utf-8")
    check("main_window.h: qt_translator member declared",
          re.search(r"^\s*QTranslator qt_translator;", hdr, re.M) is not None)

    mw = (ROOT / "src/yuzu/main_window.cpp").read_text(encoding="utf-8")
    check(
        "main_window.cpp: qtbase translator loaded in LoadTranslation",
        "#include <QLibraryInfo>" in mw
        and 'qt_translator.load(QStringLiteral("qtbase_") + qt_locale,' in mw
        and "qApp->installTranslator(&qt_translator);" in mw,
    )
    # the inserted block must be inside LoadTranslation, before the final install of `translator`
    start = mw.find("void MainWindow::LoadTranslation()")
    end = mw.find("void MainWindow::OnLanguageChanged", start)
    body = mw[start:end] if start >= 0 and end > start else ""
    check(
        "main_window.cpp: block sits inside LoadTranslation and is ordered correctly",
        body.count("{") - body.count("}") == 0
        and body.find("qt_translator.load") < body.find("qApp->installTranslator(&translator);"),
        f"function body {len(body)} chars",
    )

    # 8. the CI workflow can build translations
    wf = (ROOT / ".github/workflows/release-binaries.yml").read_text(encoding="utf-8")
    check(
        "CI installs qttools (lrelease / Qt6LinguistTools) for every aqt Qt",
        wf.count("modules: qtcharts qttools") == 3 and wf.count("install-qt-action") == 3,
    )
    check(
        "CI ships Qt's own translations next to the exe",
        "--no-translations" not in wf,
    )

    failed = [r for r in results if not r[1]]
    print()
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:")
        for name, _ok, detail in failed:
            print(f"  - {name} {detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
