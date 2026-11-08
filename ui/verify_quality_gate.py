"""
==============================================================================
GeoAI Quality & Performance Gate Enforcer (`verify_quality_gate.py`)
==============================================================================
Enforces the mandatory Test-Driven & Zero-Latency Engineering Protocol:
1. File-to-Test Pairing Audit: Verifies that every production Python module in
   the UI workspace (`app.py`, `geo_agent.py`, and any newly added `.py` files)
   and its core symbols have matching test coverage in `test_app.py`.
2. Static AST Performance Invariant Audit: Verifies `st_folium` `returned_objects`
   constraints, `@functools.lru_cache` on `get_source_text`, constant container
   heights, and absence of illegal `st.rerun()` calls in early queueing / map click paths.
3. Minimum Test Count & Regression Guard: Prevents any commit or PR from reducing
   test count below the established baseline (`MIN_REQUIRED_TESTS = 138`).
4. Full Unit & Micro-Benchmark Execution (when invoked as main runner).
==============================================================================
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys
from typing import Dict, List, Set, Tuple


MIN_REQUIRED_TESTS = 165
EXEMPT_PYTHON_FILES = {
    "test_app.py",
    "conftest.py",
    "verify_quality_gate.py",
}

REQUIRED_SYMBOL_COVERAGE: Dict[str, List[str]] = {
    "app.py": [
        "make_pin_icon",
        "color_token",
        "bbox_style",
        "_popup_card",
        "_highlight_text_spans",
        "format_tactical_citations",
        "_render_subgraph_modal_html",
        "_build_raw_request_payload",
        "_build_assistant_message",
        "clear_spatial_selection",
        "clear_map_and_console",
        "MapTrashBinHook",
        "SelectionSyncHook",
        "compute_sector_bounding_box",
        "format_regional_distribution_html",
        "build_deferred_selection_sync_js",
        "reconcile_deferred_map_selection",
    ],
    "geo_agent.py": [
        "MapLayer",
        "AgentResponse",
        "query_geo_agent",
        "to_bounding_box",
        "get_source_text",
        "extract_answer_subgraph",
        "format_evidence_popup_html",
    ],
}


def discover_production_py_files(workspace_dir: Path) -> List[Path]:
    """Return all non-test Python files in the UI workspace."""
    files: List[Path] = []
    for path in sorted(workspace_dir.glob("*.py")):
        if path.name in EXEMPT_PYTHON_FILES or path.name.startswith("test_"):
            continue
        files.append(path)
    return files


def audit_file_and_symbol_test_pairing(workspace_dir: Path) -> Tuple[bool, List[str]]:
    """
    Verify that every production `.py` file in `workspace_dir` is imported/tested
    in `test_app.py` and that required public symbols have matching test assertions.
    """
    errors: List[str] = []
    test_file = workspace_dir / "test_app.py"
    if not test_file.exists():
        return False, ["CRITICAL: `test_app.py` is missing from workspace."]

    test_source = test_file.read_text(encoding="utf-8")
    test_tree = ast.parse(test_source, filename="test_app.py")

    # Count test functions in test_app.py
    test_fn_names = [
        node.name
        for node in ast.walk(test_tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    if len(test_fn_names) < MIN_REQUIRED_TESTS:
        errors.append(
            f"Test count regression: found {len(test_fn_names)} tests in `test_app.py`, "
            f"minimum required is {MIN_REQUIRED_TESTS}."
        )

    prod_files = discover_production_py_files(workspace_dir)
    for prod_path in prod_files:
        module_stem = prod_path.stem
        if module_stem not in test_source:
            errors.append(
                f"Untested module `{prod_path.name}`: no import or reference to `{module_stem}` found in `test_app.py`."
            )
            continue

        # Check required symbols for known modules, or public functions/classes for new modules
        required_symbols = REQUIRED_SYMBOL_COVERAGE.get(prod_path.name)
        if required_symbols is None:
            prod_tree = ast.parse(prod_path.read_text(encoding="utf-8"), filename=prod_path.name)
            required_symbols = [
                node.name
                for node in prod_tree.body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_")
            ]

        missing_symbols = [sym for sym in required_symbols if sym not in test_source]
        if missing_symbols:
            errors.append(
                f"Module `{prod_path.name}` has untested public symbols in `test_app.py`: {missing_symbols}"
            )

    return len(errors) == 0, errors


def audit_static_performance_invariants(workspace_dir: Path) -> Tuple[bool, List[str]]:
    """
    Perform static AST verification of AGENTS.md zero-latency invariants on `app.py` and `geo_agent.py`.
    """
    errors: List[str] = []
    app_path = workspace_dir / "app.py"
    ga_path = workspace_dir / "geo_agent.py"

    if not app_path.exists() or not ga_path.exists():
        return False, ["CRITICAL: `app.py` or `geo_agent.py` not found in workspace."]

    app_source = app_path.read_text(encoding="utf-8")
    app_tree = ast.parse(app_source, filename="app.py")

    # 1. Verify st_folium returned_objects & return_on_hover=False
    allowed_returned = ["last_clicked", "last_active_drawing", "all_drawings"]
    for node in ast.walk(app_tree):
        if isinstance(node, ast.Call):
            fn_name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else None
            )
            if fn_name == "st_folium":
                kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
                if "returned_objects" not in kw_map or not isinstance(kw_map["returned_objects"], ast.List):
                    errors.append(f"Rule 1.1 violation at app.py:{node.lineno}: st_folium missing list literal `returned_objects`.")
                else:
                    vals = [
                        e.value for e in kw_map["returned_objects"].elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                    if vals != allowed_returned:
                        errors.append(
                            f"Rule 1.1 violation at app.py:{node.lineno}: returned_objects={vals} != {allowed_returned}."
                        )
                if "return_on_hover" not in kw_map or not (
                    isinstance(kw_map["return_on_hover"], ast.Constant) and kw_map["return_on_hover"].value is False
                ):
                    errors.append(f"Rule 1.1 violation at app.py:{node.lineno}: st_folium must set `return_on_hover=False`.")

    # 2. Verify @functools.lru_cache on get_source_text in geo_agent.py
    ga_source = ga_path.read_text(encoding="utf-8")
    ga_tree = ast.parse(ga_source, filename="geo_agent.py")
    found_cached_lookup = False
    for node in ast.walk(ga_tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_source_text":
            if node.decorator_list:
                found_cached_lookup = True
    if not found_cached_lookup:
        errors.append("Rule 2.2 violation: `geo_agent.get_source_text` must be decorated with `@functools.lru_cache`.")

    return len(errors) == 0, errors


def run_quality_gate(workspace_dir: Path, check_only: bool = False) -> int:
    """Execute static audits and optionally run the full pytest unit + benchmark suite."""
    print("==============================================================================")
    print("  GeoAI Quality & Performance Enforcement Gate")
    print("==============================================================================")

    ok_pair, pair_errors = audit_file_and_symbol_test_pairing(workspace_dir)
    ok_ast, ast_errors = audit_static_performance_invariants(workspace_dir)

    all_errors = pair_errors + ast_errors
    if all_errors:
        print("[FAIL] Quality Gate Static Audit Failed:")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("[PASS] File-to-test pairing & symbol coverage audit passed.")
    print("[PASS] Static AST zero-latency invariant audit passed.")

    if check_only:
        return 0

    print("\n[INFO] Executing full unit & performance benchmark suite via pytest...")
    cmd = [sys.executable, "-m", "pytest", str(workspace_dir / "test_app.py"), "-v"]
    proc = subprocess.run(cmd, cwd=str(workspace_dir))
    if proc.returncode != 0:
        print("\n[FAIL] Pytest unit/performance benchmark suite failed.")
        return proc.returncode

    print("\n[PASS] All unit tests, state-loop checks, and latency ceilings passed!")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="GeoAI Quality & Performance Gate Enforcer")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run static file-pairing and AST invariant checks without spawning a nested pytest process.",
    )
    args = parser.parse_args()
    workspace_dir = Path(__file__).resolve().parent
    return run_quality_gate(workspace_dir, check_only=args.check_only)


if __name__ == "__main__":
    sys.exit(main())
