"""
Runner Agent  v2.0
==================
Writes every file in the project to a single clean root folder,
installs dependencies, then executes the entry point exactly as a
developer would from their terminal — capturing real stdout/stderr.

Key guarantees:
  ✔ All files land in one root dir  → sibling imports always work
  ✔ PYTHONPATH includes root dir    → cross-file imports always resolve
  ✔ Files verified after write      → no silent write failures
  ✔ Syntax pre-check (Python)       → SyntaxErrors caught before running
  ✔ has_error uses exit_code first  → warnings in stderr ≠ broken code
  ✔ Tmpdir paths stripped from output → agents see clean relative paths
  ✔ Nested paths (src/utils.py) supported → subdirs created automatically
"""

import os
import re
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional


# ── Language run commands ─────────────────────────────────────────────────────

RUN_COMMANDS = {
    "python":     ["python3", "{entry}"],
    "javascript": ["node",    "{entry}"],
    "typescript": ["npx",     "ts-node", "{entry}"],
    "ruby":       ["ruby",    "{entry}"],
    "go":         ["go",      "run",     "{entry}"],
    "bash":       ["bash",    "{entry}"],
}

# ── Dependency install commands ───────────────────────────────────────────────

INSTALL_COMMANDS = {
    "requirements.txt": ["pip3", "install", "-r", "requirements.txt", "--quiet", "--no-warn-script-location"],
    "package.json":     ["npm",  "install", "--silent"],
    "Pipfile":          ["pipenv", "install", "--quiet"],
    "pyproject.toml":   ["pip3", "install", ".", "--quiet"],
    "go.mod":           ["go",   "mod",     "download"],
}

# ── Stderr patterns that are warnings, not real errors ───────────────────────
# If exit_code == 0 these patterns in stderr should NOT mark the run as broken.

WARNING_ONLY_PATTERNS = [
    r"DeprecationWarning",
    r"PendingDeprecationWarning",
    r"FutureWarning",
    r"UserWarning",
    r"ResourceWarning",
    r"InsecureRequestWarning",
    r"^\s*warnings\.warn\(",
    r"pip.*WARNING",
    r"npm warn",
    r"^\s*$",   # blank lines
]

TIMEOUT = 30   # seconds for the actual run
INSTALL_TIMEOUT = 120


# ── Public API ────────────────────────────────────────────────────────────────

def run_project(file_tree: dict, entry_point: str, language: str = "auto") -> dict:
    """
    1. Creates a clean root project directory.
    2. Writes every file from file_tree into it (respecting subdirectory paths).
    3. Verifies every file was written correctly.
    4. Installs dependencies if a manifest is present.
    5. Runs a syntax pre-check (Python only) before executing.
    6. Executes the entry point and captures real terminal output.
    7. Strips tmpdir absolute paths from stderr so agents see clean paths.

    Returns:
    {
        "stdout":          str,
        "stderr":          str,   # clean — no tmpdir paths
        "exit_code":       int,
        "ran":             bool,
        "install_output":  str,
        "error":           str | None,
        "files_written":   list[str],
        "root_dir":        str,   # always "project_root/" (relative label)
        "pre_check_error": str,   # non-empty if syntax pre-check failed
    }
    """
    tmpdir = tempfile.mkdtemp(prefix="stackheal_")
    # All project files live under project_root/ inside tmpdir
    root = os.path.join(tmpdir, "project_root")
    os.makedirs(root, exist_ok=True)

    result: dict = {
        "stdout":          "",
        "stderr":          "",
        "exit_code":       -1,
        "ran":             False,
        "install_output":  "",
        "error":           None,
        "files_written":   [],
        "root_dir":        "project_root/",
        "pre_check_error": "",
    }

    try:
        # ── Step 1: Write all files ───────────────────────────────────────────
        write_errors = _write_files(file_tree, root, result)
        if write_errors:
            result["error"] = "File write failures:\n" + "\n".join(write_errors)
            return result

        # ── Step 2: Install dependencies ─────────────────────────────────────
        _install_dependencies(file_tree, root, result)

        # ── Step 3: Resolve language ──────────────────────────────────────────
        if language in ("auto", None, ""):
            language = _detect_language_from_entry(entry_point)
        lang_key = language.lower()
        if lang_key not in RUN_COMMANDS:
            lang_key = "python"

        # ── Step 4: Syntax pre-check (Python only) ────────────────────────────
        if lang_key == "python":
            pre_err = _python_syntax_check(root, entry_point, result)
            if pre_err:
                # Syntax error found — no point running, return immediately
                return result

        # ── Step 5: Build run command ─────────────────────────────────────────
        cmd_template = RUN_COMMANDS[lang_key]
        cmd = [part.replace("{entry}", entry_point) for part in cmd_template]

        # ── Step 6: Set environment ───────────────────────────────────────────
        env = _build_env(root, lang_key)

        # ── Step 7: Execute ───────────────────────────────────────────────────
        proc = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )

        result["stdout"]    = proc.stdout
        # Strip root first (longer path), then tmpdir — order matters
        result["stderr"]    = _sanitize_paths(proc.stderr, root, tmpdir)
        result["exit_code"] = proc.returncode
        result["ran"]       = True

    except subprocess.TimeoutExpired:
        result["error"]     = f"Execution timed out after {TIMEOUT} seconds"
        result["exit_code"] = -1

    except FileNotFoundError as exc:
        runtime = RUN_COMMANDS.get(language.lower(), ["<unknown>"])[0]
        result["error"] = (
            f"Runtime '{runtime}' not found on this system.\n"
            f"Install it or check PATH.\nDetail: {exc}"
        )

    except Exception as exc:
        result["error"] = str(exc)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return result


def has_error(run_result: dict) -> bool:
    """
    Returns True only when there is a REAL error.

    Rules (in priority order):
      1. Runner-level error (runtime not found, timeout, write failure) → always True
      2. Syntax pre-check failed → True
      3. exit_code != 0 → True  (the real signal)
      4. exit_code == 0 + stderr has only warnings → False  (clean run with noise)
      5. exit_code == 0 + stderr has real error lines → True  (edge case: some
         tools write errors to stderr but exit 0 — e.g. pytest failures, node)
    """
    if run_result.get("error"):
        return True
    if run_result.get("pre_check_error"):
        return True

    exit_code = run_result.get("exit_code", -1)

    # Didn't run at all
    if not run_result.get("ran") and exit_code == -1:
        return True

    if exit_code != 0:
        return True

    # exit_code == 0 — check if stderr contains real errors vs just warnings
    stderr = run_result.get("stderr", "").strip()
    if not stderr:
        return False

    return _stderr_has_real_error(stderr)


def build_execution_report(run_result: dict) -> str:
    """
    Builds a clean, readable summary string for downstream agents.
    Includes file list, install output, stdout, stderr, and exit code.
    """
    lines = []

    written = run_result.get("files_written", [])
    if written:
        lines.append(f"[PROJECT FILES WRITTEN TO {run_result.get('root_dir', 'project_root/')}]")
        for f in written:
            lines.append(f"  ✓ {f}")

    pre_err = run_result.get("pre_check_error", "")
    if pre_err:
        lines.append(f"[SYNTAX PRE-CHECK FAILED]\n{pre_err}")

    install = run_result.get("install_output", "").strip()
    if install:
        lines.append(f"[INSTALL OUTPUT]\n{install[:600]}")

    stdout = run_result.get("stdout", "").strip()
    if stdout:
        lines.append(f"[STDOUT]\n{stdout[:2000]}")

    stderr = run_result.get("stderr", "").strip()
    if stderr:
        lines.append(f"[STDERR]\n{stderr[:2000]}")

    runner_err = run_result.get("error", "")
    if runner_err:
        lines.append(f"[RUNNER ERROR]\n{runner_err}")

    lines.append(f"[EXIT CODE] {run_result.get('exit_code', -1)}")

    return "\n\n".join(lines) if lines else "No output captured"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _write_files(file_tree: dict, root: str, result: dict) -> list:
    """
    Write every file from file_tree into root.
    Handles flat filenames and nested paths (src/utils.py).
    Verifies each file after writing.
    Returns a list of error strings (empty = all good).
    """
    errors = []
    for filename, content in file_tree.items():
        if not filename or not filename.strip():
            continue

        # Normalise separators and strip any leading slash / drive letter
        clean_name = filename.replace("\\", "/").lstrip("/")
        filepath   = os.path.join(root, *clean_name.split("/"))

        # Create parent directories
        parent = os.path.dirname(filepath)
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception as exc:
            errors.append(f"  Could not create directory for '{filename}': {exc}")
            continue

        # Write file
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(content or "")
        except Exception as exc:
            errors.append(f"  Could not write '{filename}': {exc}")
            continue

        # Verify it landed correctly
        if not os.path.isfile(filepath):
            errors.append(f"  '{filename}' was written but cannot be found at {filepath}")
            continue

        on_disk_size = os.path.getsize(filepath)
        expected_size = len((content or "").encode("utf-8"))
        if on_disk_size != expected_size:
            errors.append(
                f"  '{filename}' size mismatch: wrote {expected_size} bytes, "
                f"found {on_disk_size} bytes on disk"
            )
            continue

        result["files_written"].append(clean_name)

    return errors


def _install_dependencies(file_tree: dict, root: str, result: dict) -> None:
    """Install deps if a manifest is present in the file_tree."""
    for manifest, cmd in INSTALL_COMMANDS.items():
        if manifest in file_tree:
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=INSTALL_TIMEOUT,
                )
                result["install_output"] = (proc.stdout + proc.stderr).strip()
            except subprocess.TimeoutExpired:
                result["install_output"] = f"Dependency install timed out after {INSTALL_TIMEOUT}s"
            except FileNotFoundError:
                result["install_output"] = (
                    f"Install tool '{cmd[0]}' not found — "
                    f"dependencies from '{manifest}' were not installed."
                )
            break  # only process one manifest


def _python_syntax_check(root: str, entry_point: str, result: dict) -> bool:
    """
    Run `python3 -m py_compile <entry>` for every .py file.
    Populates result["pre_check_error"] and result["stderr"] if any fail.
    Returns True if a syntax error was found (caller should abort execution).
    """
    py_files = [f for f in os.listdir(root) if f.endswith(".py")]
    # Always check the entry point first
    ordered = []
    ep_base = os.path.basename(entry_point)
    if ep_base in py_files:
        ordered.append(ep_base)
    for f in py_files:
        if f not in ordered:
            ordered.append(f)

    for pyfile in ordered:
        proc = subprocess.run(
            ["python3", "-m", "py_compile", pyfile],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            err = _sanitize_paths(proc.stderr or proc.stdout, root, root).strip()
            result["pre_check_error"] = err
            result["stderr"]          = err
            result["exit_code"]       = proc.returncode
            result["ran"]             = False
            return True

    return False


def _build_env(root: str, lang_key: str) -> dict:
    """
    Build an environment dict for the subprocess.
    Adds root to PYTHONPATH (Python) or NODE_PATH (JS) so every
    sibling file is importable without any sys.path manipulation.
    """
    env = os.environ.copy()

    if lang_key == "python":
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")

    elif lang_key in ("javascript", "typescript"):
        existing = env.get("NODE_PATH", "")
        env["NODE_PATH"] = root + (os.pathsep + existing if existing else "")

    return env


def _sanitize_paths(text: str, *paths_to_strip: str) -> str:
    """
    Replace absolute tmpdir paths in output with relative equivalents.
    e.g. /tmp/stackheal_abc/project_root/main.py  →  main.py
         /tmp/stackheal_abc/project_root/          →  (empty)
    """
    result = text
    for path in paths_to_strip:
        if path:
            # Replace path + separator
            result = re.sub(re.escape(path).rstrip("/\\\\") + r"[/\\\\]?", "", result)
    return result


def _detect_language_from_entry(entry_point: str) -> str:
    ext = Path(entry_point).suffix.lower()
    mapping = {
        ".py":  "python",
        ".js":  "javascript",
        ".ts":  "typescript",
        ".rb":  "ruby",
        ".go":  "go",
        ".sh":  "bash",
    }
    return mapping.get(ext, "python")


def _stderr_has_real_error(stderr: str) -> bool:
    """
    Returns True if stderr contains real error lines, not just warnings.
    Used only when exit_code == 0 but stderr is non-empty.
    """
    warning_re = re.compile(
        "|".join(WARNING_ONLY_PATTERNS), re.IGNORECASE | re.MULTILINE
    )
    for line in stderr.splitlines():
        line = line.strip()
        if not line:
            continue
        if not warning_re.search(line):
            # Found a line that isn't a warning pattern → real error
            return True
    return False


# ── Quick self-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("TEST 1: Multi-file project with sibling import (should PASS)")
    files1 = {
        "main.py":  "from utils import greet\ngreet()\nprint('done')",
        "utils.py": "def greet():\n    print('Hello from utils!')",
    }
    r1 = run_project(files1, "main.py", "python")
    print("  Files written:", r1["files_written"])
    print("  stdout:", r1["stdout"].strip())
    print("  stderr:", r1["stderr"].strip() or "(none)")
    print("  exit_code:", r1["exit_code"])
    print("  has_error:", has_error(r1))

    print()
    print("=" * 60)
    print("TEST 2: Missing module (should FAIL with ModuleNotFoundError)")
    files2 = {
        "main.py": "from STT import recognize\nrecognize()",
    }
    r2 = run_project(files2, "main.py", "python")
    print("  Files written:", r2["files_written"])
    print("  stderr:", r2["stderr"].strip())
    print("  exit_code:", r2["exit_code"])
    print("  has_error:", has_error(r2))

    print()
    print("=" * 60)
    print("TEST 3: SyntaxError caught by pre-check (should FAIL fast)")
    files3 = {
        "main.py": "def broken(\n  print('oops')",
    }
    r3 = run_project(files3, "main.py", "python")
    print("  pre_check_error:", r3["pre_check_error"])
    print("  ran:", r3["ran"])
    print("  has_error:", has_error(r3))

    print()
    print("=" * 60)
    print("TEST 4: Warning-only stderr with exit 0 (should be CLEAN)")
    files4 = {
        "main.py": (
            "import warnings\n"
            "warnings.warn('deprecated', DeprecationWarning)\n"
            "print('all good')"
        ),
    }
    r4 = run_project(files4, "main.py", "python")
    print("  stdout:", r4["stdout"].strip())
    print("  stderr:", r4["stderr"].strip())
    print("  exit_code:", r4["exit_code"])
    print("  has_error:", has_error(r4), "(should be False)")

    print()
    print("=" * 60)
    print("TEST 5: KeyError at runtime in multi-file project")
    files5 = {
        "main.py":   "from data import get_df\ndf = get_df()\nprint(df['missing_col'])",
        "data.py":   "import pandas as pd\ndef get_df():\n    return pd.DataFrame({'a': [1,2,3]})",
    }
    r5 = run_project(files5, "main.py", "python")
    print("  Files written:", r5["files_written"])
    print("  stderr:", r5["stderr"].strip())
    print("  exit_code:", r5["exit_code"])
    print("  has_error:", has_error(r5))