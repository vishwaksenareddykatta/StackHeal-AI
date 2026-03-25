"""
Error Dataset Matcher
Checks stderr/code against the predefined python_errors.json dataset FIRST,
before making any AI call. This gives instant, accurate results for all known
Python errors (ModuleNotFoundError, ImportError, SyntaxError, etc.)

Why this fixes the dummyclient.py problem:
  dummyclient.py has: from STT import ... and from testttss import ...
  When it runs, Python raises:  ModuleNotFoundError: No module named 'STT'
  The old pipeline returned "UnknownError" because the AI misclassified it.
  This module matches "No module named" → ModuleNotFoundError instantly.
"""

import json
import os
import re
from typing import Optional


# ── Load dataset once at import time ──────────────────────────────────────────
_DATASET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_errors.json")

try:
    with open(_DATASET_PATH, "r", encoding="utf-8") as _f:
        _DATASET = json.load(_f)["errors"]
except Exception as _e:
    print(f"[ErrorDataset] Warning: Could not load python_errors.json: {_e}")
    _DATASET = {}


def match_error(text: str) -> Optional[dict]:
    """
    Try to match `text` (stderr, error message, or code) against the dataset.

    Returns a full result dict if matched, or None if no confident match.

    The result dict is in the same shape as what AI agents return, so it's a
    drop-in replacement for the entire 7-agent pipeline for known errors.
    """
    if not text or not text.strip():
        return None

    text_lower = text.lower()

    # ── Scan every error type in priority order ───────────────────────────────
    # Priority: most specific first (custom_module_error before ModuleNotFoundError)
    priority_order = [
        "custom_module_error",
        "ModuleNotFoundError",
        "ImportError",
        "SyntaxError",
        "IndentationError",
        "TabError",
        "ZeroDivisionError",
        "AttributeError",
        "NameError",
        "KeyError",
        "IndexError",
        "TypeError",
        "ValueError",
        "FileNotFoundError",
        "PermissionError",
        "RecursionError",
        "MemoryError",
        "TimeoutError",
        "ConnectionError",
        "JSONDecodeError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "StopIteration",
        "AssertionError",
        "NotImplementedError",
        "RuntimeError",
        "OverflowError",
        "SystemExit",
        "KeyboardInterrupt",
        "EOFError",
        "OSError",
        "IsADirectoryError",
        "NotADirectoryError",
        "BlockingIOError",
        "ChildProcessError",
        "DeprecationWarning",
        "FutureWarning",
        "ResourceWarning",
        "pickle.UnpicklingError",
        "ssl.SSLError",
        "subprocess.CalledProcessError",
        "requests.exceptions.ConnectionError",
        "requests.exceptions.HTTPError",
    ]

    for error_key in priority_order:
        entry = _DATASET.get(error_key)
        if not entry:
            continue

        patterns = entry.get("patterns", [])
        matched = any(pat.lower() in text_lower for pat in patterns)

        if not matched:
            # Also try regex patterns
            for pat in patterns:
                try:
                    if re.search(pat, text, re.IGNORECASE):
                        matched = True
                        break
                except re.error:
                    pass

        if matched:
            return _build_result(error_key, entry, text)

    return None


def _build_result(error_key: str, entry: dict, text: str) -> dict:
    """
    Build a full result dict from the matched dataset entry.
    Extracts specific details (module name, line number) from the text where possible.
    """
    # ── Extract module name for ModuleNotFoundError / ImportError ─────────────
    module_name = _extract_module_name(text)
    line_number = _extract_line_number(text)
    snippet     = _extract_snippet(text)

    # ── Build root cause ──────────────────────────────────────────────────────
    root_cause_tpl = entry.get("root_cause_template", entry.get("root_cause", ""))
    root_cause     = root_cause_tpl

    # Check common_modules for a better fix hint
    fix_hint = ""
    if module_name:
        root_cause = root_cause_tpl.replace("{module}", module_name).replace("{name}", module_name)
        common_mods = entry.get("common_modules", {})
        fix_hint = common_mods.get(module_name, entry.get("fix_template", "").replace("{module}", module_name))
    
    root_cause = root_cause.replace("{line}", str(line_number)).replace("{index}", "?").replace("{length}", "?").replace("{attr}", "?").replace("{key}", "?").replace("{path}", "?").replace("{encoding}", "utf-8").replace("{url}", "?").replace("{code}", "?")

    description = fix_hint if fix_hint else entry.get("fix_template", "")
    if not description:
        description = entry.get("simple", "")

    corrected_code = ""
    if fix_hint and module_name:
        # If it's a pip install fix
        if "pip install" in fix_hint:
            corrected_code = f"# In your terminal:\n{fix_hint}"
        elif module_name + ".py" in fix_hint or "sys.path" in fix_hint:
            corrected_code = fix_hint

    return {
        # Core error info
        "type":          error_key.split(".")[-1],   # short name
        "message":       _extract_error_message(text) or f"{error_key.split('.')[-1]} detected",
        "line":          line_number,
        "snippet":       snippet,
        "severity":      entry.get("severity", "Medium"),
        "language":      entry.get("language", "Python"),
        "root_cause":    root_cause,
        "description":   description,
        "correctedCode": corrected_code,

        # Explanation
        "simple":    entry.get("simple", ""),
        "detailed":  entry.get("detailed", ""),

        # Confidence is high for dataset matches
        "confidence":        0.95,
        "detection_source":  "dataset",
    }


# ── Text extraction helpers ───────────────────────────────────────────────────

def _extract_module_name(text: str) -> str:
    """Extract module name from 'No module named X' or 'cannot import name X from Y'."""
    patterns = [
        r"No module named ['\"]?([a-zA-Z0-9_\.]+)['\"]?",
        r"cannot import name ['\"]?([a-zA-Z0-9_\.]+)['\"]? from ['\"]?([a-zA-Z0-9_\.]+)['\"]?",
        r"ImportError.*['\"]([a-zA-Z0-9_\.]+)['\"]",
        r"ModuleNotFoundError.*['\"]([a-zA-Z0-9_\.]+)['\"]",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _extract_line_number(text: str) -> int:
    """Extract line number from traceback or error message."""
    patterns = [
        r"line (\d+)",
        r"File .+, line (\d+)",
        r", line (\d+)[,\s]",
        r"at line (\d+)",
        r":(\d+):",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return -1


def _extract_snippet(text: str) -> str:
    """Try to extract the specific failing line from a traceback."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Traceback "    result = df['b'].sum()" style
        if stripped and not stripped.startswith(("File ", "Traceback", "#")) and i > 0:
            prev = lines[i - 1].strip()
            if prev.startswith("File ") or "line" in prev.lower():
                return stripped
    return ""


def _extract_error_message(text: str) -> str:
    """Extract the last error line from a traceback."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Last non-empty line is usually the error message
    for line in reversed(lines):
        if any(err in line for err in [
            "Error:", "Exception:", "Warning:", "Error ", "exception"
        ]):
            return line[:200]
    # Fallback: last line
    return lines[-1][:200] if lines else ""


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        "ModuleNotFoundError: No module named 'STT'",
        "ModuleNotFoundError: No module named 'pandas'",
        "ZeroDivisionError: division by zero",
        "SyntaxError: invalid syntax (main.py, line 4)",
        "KeyError: 'b'",
        "Everything ran fine, no errors",
        "AttributeError: 'NoneType' object has no attribute 'profile'",
        "Traceback (most recent call last):\n  File \"main.py\", line 3, in <module>\n    result = df['b'].sum()\nKeyError: 'b'",
    ]
    for t in tests:
        r = match_error(t)
        if r:
            print(f"✅ MATCHED: {r['type']} | conf={r['confidence']} | {r['message'][:60]}")
        else:
            print(f"❌ NO MATCH: {t[:60]}")
