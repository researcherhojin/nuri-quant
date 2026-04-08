#!/usr/bin/env python3
"""Test file consolidation script.

Extracts test classes from source files and groups them by domain.
Uses AST parsing to safely extract classes with their full source text.

Usage:
    python scripts/consolidate_tests.py --domain scheduler --dry-run
    python scripts/consolidate_tests.py --domain scheduler --execute
"""

import argparse
import ast
from collections import defaultdict
from pathlib import Path

TESTS_DIR = Path(__file__).parent.parent / "tests"

# Domain → module prefixes mapping
DOMAIN_MODULES = {
    "scheduler": ["nuri.scheduler"],
    "alerts": ["nuri.alerts"],
    "llm": ["nuri.llm"],
    "api": ["nuri.api"],
    "analysis": ["nuri.analysis"],
    "trading_engine": ["nuri.trading.engine", "nuri.trading.execution"],
    "trading_recommend": ["nuri.trading.recommend"],
    "trading_agents": ["nuri.trading.agents"],
    "trading_strategy": ["nuri.trading.strategy", "nuri.trading.swing"],
    "collectors": ["nuri.collectors"],
    "quant": ["nuri.quant"],
}

# Files to keep as-is (never touch)
KEEP_FILES = {
    "conftest.py",
    "test_db.py",
    "test_timezone.py",
    "test_pipeline_events.py",
    "test_pipeline_api.py",
    "test_investment_rules.py",
    "test_portfolio_sync.py",
    "test_data_integrity.py",
}

# Target filenames
DOMAIN_TARGET = {
    "scheduler": "test_scheduler_all.py",
    "alerts": "test_alerts_all.py",
    "llm": "test_llm_all.py",
    "api": "test_api_all.py",
    "analysis": "test_analysis_all.py",
    "trading_engine": "test_trading_engine_all.py",
    "trading_recommend": "test_trading_recommend_all.py",
    "trading_agents": "test_trading_agents_all.py",
    "trading_strategy": "test_trading_strategy_all.py",
    "collectors": "test_collectors_all.py",
    "quant": "test_quant_all.py",
}


def get_source_files():
    """Get all test files that are candidates for consolidation."""
    all_files = sorted(TESTS_DIR.glob("test_*.py"))
    return [f for f in all_files if f.name not in KEEP_FILES]


def classify_class_domain(class_source: str) -> str | None:
    """Determine which domain a test class belongs to based on its imports."""
    # Check imports within the class source
    for domain, prefixes in DOMAIN_MODULES.items():
        for prefix in prefixes:
            # Check for: from nuri.xxx import, import nuri.xxx, nuri.xxx.yyy as
            if f"nuri.{prefix.split('nuri.')[-1]}" in class_source:
                return domain
            if prefix in class_source:
                return domain

    return None


def extract_classes_with_context(filepath: Path) -> list[dict]:
    """Extract test classes from a file with their source text and domain."""
    source = filepath.read_text()
    lines = source.splitlines(keepends=True)

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        print(f"  SKIP (syntax error): {filepath.name}")
        return []

    classes = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            # Get the source lines for this class
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, "end_lineno") else start + 1

            # Include any decorators
            if node.decorator_list:
                start = min(d.lineno - 1 for d in node.decorator_list)

            class_source = "".join(lines[start:end])

            # Count test methods
            test_count = sum(
                1
                for child in ast.walk(node)
                if isinstance(child, ast.FunctionDef) and child.name.startswith("test_")
            )

            domain = classify_class_domain(class_source)

            # If class itself doesn't have imports, check file-level imports
            if domain is None:
                domain = classify_class_domain(source)

            classes.append({
                "name": node.name,
                "source": class_source,
                "test_count": test_count,
                "domain": domain,
                "file": filepath.name,
                "start_line": start + 1,
                "end_line": end,
            })

    return classes


def get_file_imports_and_helpers(filepath: Path) -> tuple[list[str], list[str]]:
    """Extract top-level imports and helper functions from a file."""
    source = filepath.read_text()
    lines = source.splitlines(keepends=True)

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return [], []

    imports = []
    helpers = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, "end_lineno") else start + 1
            imports.append("".join(lines[start:end]).rstrip())
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("test_"):
            start = node.lineno - 1
            if node.decorator_list:
                start = min(d.lineno - 1 for d in node.decorator_list)
            end = node.end_lineno if hasattr(node, "end_lineno") else start + 1
            helpers.append("".join(lines[start:end]))
        elif isinstance(node, ast.Assign):
            # Module-level assignments (constants, fixtures defined as assignments)
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, "end_lineno") else start + 1
            text = "".join(lines[start:end]).strip()
            if not text.startswith("#"):
                helpers.append("".join(lines[start:end]))

    return imports, helpers


def resolve_suffix(filename: str) -> str:
    """Generate a suffix for duplicate class names based on source file."""
    base = filename.replace("test_", "").replace(".py", "")
    if "coverage_round" in base:
        return base.replace("coverage_round", "R")
    elif "coverage_" in base:
        return base.replace("coverage_", "").title()
    else:
        parts = base.split("_")
        return "".join(p.title() for p in parts)


def consolidate_domain(domain: str, dry_run: bool = True):
    """Consolidate all test classes for a domain into one file."""
    target = DOMAIN_TARGET[domain]
    prefixes = DOMAIN_MODULES[domain]
    source_files = get_source_files()

    print(f"\n{'='*60}")
    print(f"  Domain: {domain} → {target}")
    print(f"  Module prefixes: {prefixes}")
    print(f"{'='*60}")

    # Collect all classes for this domain
    domain_classes = []
    source_files_used = set()

    for filepath in source_files:
        classes = extract_classes_with_context(filepath)
        for cls in classes:
            if cls["domain"] == domain:
                domain_classes.append(cls)
                source_files_used.add(filepath.name)

    if not domain_classes:
        print("  No classes found for this domain.")
        return

    # Report
    total_tests = sum(c["test_count"] for c in domain_classes)
    print(f"\n  Found {len(domain_classes)} classes, {total_tests} tests from {len(source_files_used)} files:")
    for cls in domain_classes:
        print(f"    {cls['file']}::{cls['name']} ({cls['test_count']} tests)")

    if dry_run:
        print(f"\n  [DRY RUN] Would create {target} with {total_tests} tests")
        return

    # Handle duplicates
    name_counts = defaultdict(int)
    for cls in domain_classes:
        name_counts[cls["name"]] += 1

    duplicates = {name for name, count in name_counts.items() if count > 1}
    if duplicates:
        print(f"\n  Duplicate class names: {duplicates}")
        # Rename all but the first occurrence
        seen = set()
        for cls in domain_classes:
            if cls["name"] in duplicates:
                if cls["name"] in seen:
                    suffix = resolve_suffix(cls["file"])
                    old_name = cls["name"]
                    new_name = f"{old_name}_{suffix}"
                    cls["source"] = cls["source"].replace(
                        f"class {old_name}", f"class {new_name}", 1
                    )
                    cls["name"] = new_name
                    print(f"    Renamed: {old_name} → {new_name} (from {cls['file']})")
                else:
                    seen.add(cls["name"])

    print(f"\n  Creating {target}...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consolidate test files by domain")
    parser.add_argument("--domain", required=True, choices=DOMAIN_MODULES.keys())
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    consolidate_domain(args.domain, dry_run=not args.execute)
