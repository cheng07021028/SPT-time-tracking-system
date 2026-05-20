# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
SERVICES = ROOT / "services"

REQ_MASTER_FUNCS = [
    "load_employees_for_time_record_fast",
    "load_work_orders_for_time_record_fast",
    "has_master_data_for_time_record_fast",
]


def parse(path: Path):
    return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))


def func_defs(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
    return out


def button_callbacks(tree: ast.AST) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            fn = node.func
            is_button = isinstance(fn, ast.Attribute) and fn.attr == "button"
            if is_button:
                for kw in node.keywords:
                    if kw.arg == "on_click" and isinstance(kw.value, ast.Name):
                        out.append((kw.value.id, getattr(node, "lineno", 0)))
            self.generic_visit(node)
    V().visit(tree)
    return out


def main() -> int:
    problems: list[str] = []
    print("=== V31 button/page diagnostic ===")
    files = sorted(PAGES.glob("*.py"))
    print(f"pages: {len(files)}")
    for p in files:
        print(f" - {p.name}")
    # detect duplicate numeric prefixes
    by_prefix: dict[str, list[str]] = {}
    for p in files:
        prefix = p.name.split(".", 1)[0].strip()
        by_prefix.setdefault(prefix, []).append(p.name)
    for prefix, names in sorted(by_prefix.items()):
        if len(names) > 1:
            problems.append(f"DUPLICATE_PAGE_PREFIX {prefix}: {names}")
    for p in files:
        try:
            tree = parse(p)
        except Exception as e:
            problems.append(f"PAGE_PARSE_ERROR {p.name}: {e}")
            continue
        defs = func_defs(tree)
        for cb, line in button_callbacks(tree):
            if cb not in defs:
                problems.append(f"MISSING_CALLBACK {p.name}:{line} on_click={cb}")
    mds = SERVICES / "master_data_service.py"
    try:
        txt = mds.read_text(encoding="utf-8", errors="ignore")
        for name in REQ_MASTER_FUNCS:
            if f"def {name}" not in txt:
                problems.append(f"MISSING_MASTER_DATA_FUNC {name}")
    except Exception as e:
        problems.append(f"MASTER_DATA_READ_ERROR {e}")
    if problems:
        print("FAIL")
        for p in problems:
            print(p)
        return 1
    print("PASS: no duplicate page prefix, no missing button callbacks, required master data wrappers exist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
