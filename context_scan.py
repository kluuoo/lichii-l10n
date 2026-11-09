"""Resolve the Qt translation context of every tr() call the way lupdate does.

lupdate uses the enclosing class of the function that contains the call; for code
outside a class it uses the enclosing namespace chain. A naive "last Class::method("
scan picks up calls such as QMessageBox::warning(, so this module builds a code-only
view of each file, finds function bodies, class bodies and namespaces by brace
matching, and assigns the innermost enclosing scope.

Files that route tr() through a local lambda built on QCoreApplication::translate
(shared_translation.cpp) get the lambda's explicit context instead.
"""
from __future__ import annotations

import re

FUNC_DEF = re.compile(r"\b([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*::\s*(~?[A-Za-z_]\w*)\s*\(")
CLASS_START = re.compile(
    r"\b(?:class|struct)\s+(?:alignas\([^)]*\)\s*)?([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^;{()]*)?\{"
)
NAMESPACE_START = re.compile(r"\bnamespace\s+([A-Za-z_]\w*)?\s*\{")
TR_LAMBDA = re.compile(
    r"\btr\s*=\s*\[[^\]]*\]\s*\([^)]*\)[^{;]*\{\s*return\s+QCoreApplication::translate\(\s*\"([^\"]+)\""
)


def code_only(text: str) -> str:
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if c == '"' or (c == "R" and nxt == '"' and (i == 0 or not text[i - 1].isalnum())):
            start = i
            if c == "R":
                m = re.match(r'R"([^(]{0,16})\(', text[i:])
                delim = m.group(1) if m else ""
                end_tok = ")" + delim + '"'
                j = text.find(end_tok, i + (len(m.group(0)) if m else 2))
                j = n if j < 0 else j + len(end_tok)
            else:
                j = i + 1
                while j < n:
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == '"':
                        j += 1
                        break
                    j += 1
            for k in range(start, min(j, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "'":
                    j += 1
                    break
                j += 1
            for k in range(i, min(j, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def match_close(code: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(start, len(code)):
        if code[i] == open_ch:
            depth += 1
        elif code[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def body_brace(code: str, pos: int) -> int:
    """First '{' that opens a function body, skipping over an initializer list."""
    depth = 0
    i = pos
    while i < len(code):
        c = code[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0:
            if c == ";":
                return -1
            if c == "}":
                return -1
            if c == "{":
                return i
        i += 1
    return -1


def scopes(text: str):
    """Return (start, end, name, kind) with kind in {function, class, namespace}."""
    code = code_only(text)
    found = []

    for m in FUNC_DEF.finditer(code):
        cls = m.group(1).split("::")[-1]
        popen = code.find("(", m.start())
        pclose = match_close(code, popen, "(", ")")
        if pclose < 0:
            continue
        bstart = body_brace(code, pclose + 1)
        if bstart < 0:
            continue
        bend = match_close(code, bstart, "{", "}")
        if bend < 0:
            continue
        found.append((bstart, bend, cls, "function"))

    for m in CLASS_START.finditer(code):
        bstart = code.find("{", m.end() - 1)
        bend = match_close(code, bstart, "{", "}")
        if bend < 0:
            continue
        found.append((bstart, bend, m.group(1), "class"))

    for m in NAMESPACE_START.finditer(code):
        bstart = code.find("{", m.start())
        bend = match_close(code, bstart, "{", "}")
        if bend < 0:
            continue
        found.append((bstart, bend, m.group(1) or "", "namespace"))

    return found


def lambda_context(text: str) -> str:
    m = TR_LAMBDA.search(text)
    return m.group(1) if m else ""


def context_at(scope_list, pos: int, ns_chain=None) -> str:
    """Innermost enclosing class; otherwise the innermost namespace chain."""
    best = None
    best_size = None
    for start, end, name, kind in scope_list:
        if start <= pos <= end and kind in ("function", "class"):
            size = end - start
            if best_size is None or size < best_size:
                best, best_size = name, size
    if best:
        return best

    chain = []
    for start, end, name, kind in scope_list:
        if kind == "namespace" and start <= pos <= end:
            chain.append((end - start, name))
    chain.sort(reverse=True)
    names = [name for _size, name in chain if name]
    if names:
        return "::".join(names)
    return ns_chain or ""
