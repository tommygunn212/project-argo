# core/codebase_stats.py
"""
Deterministic codebase statistics for ARGO.
This module is imported by pipeline.py for canonical self-reporting.
"""
import os
from pathlib import Path

def get_codebase_stats(root_dir=None):
    """Return a dict with lines of code, file count, and Python file count."""
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent
    py_count = 0
    py_lines = 0
    total_files = 0
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            total_files += 1
            if fname.endswith('.py'):
                py_count += 1
                try:
                    with open(os.path.join(dirpath, fname), encoding='utf-8', errors='ignore') as f:
                        py_lines += sum(1 for _ in f)
                except Exception:
                    pass
    return {
        'total_files': total_files,
        'python_files': py_count,
        'python_lines': py_lines,
    }

def format_codebase_stats(stats):
    return (
        f"ARGO codebase: {stats['python_files']} Python files, {stats['python_lines']} lines of Python code, "
        f"{stats['total_files']} total files in workspace."
    )
