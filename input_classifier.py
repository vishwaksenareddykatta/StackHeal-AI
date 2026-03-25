"""
Input Classifier
Detects what kind of input was received and normalizes it
into a standard format for the unified pipeline.

Input types:
  - SNIPPET  → raw code string or error message (no file_tree)
  - FILE     → single file submitted as file_tree with 1 entry
  - REPO     → multiple files submitted as file_tree

Each type gets normalized into:
  {
    "input_type": "snippet" | "file" | "repo",
    "file_tree": { filename: content },   # always populated
    "raw_input": str,                     # original text if snippet
    "entry_point": str | None,
    "language": str,
    "total_tokens_estimate": int
  }
"""

import os
from pathlib import Path
from typing import Optional


# Rough token estimate: 1 token ≈ 4 chars
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# Files that are never useful to agents (binary, lock files, assets, etc.)
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".mp3", ".wav", ".avi",
    ".zip", ".tar", ".gz", ".rar",
    ".lock", ".sum",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".DS_Store", ".env",
}

SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock",
    ".gitignore", ".dockerignore", "LICENSE", "LICENCE",
    "CHANGELOG.md", "CHANGELOG.txt",
}

# Extensions that are always useful
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rb", ".java",
    ".cpp", ".c", ".cs", ".php", ".rs", ".swift", ".kt",
    ".html", ".css", ".scss", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".env.example", ".sh", ".bash",
    ".md", ".txt", ".sql",
}

# Max tokens to send to any single agent call
AGENT_TOKEN_BUDGET = 6000

# Max tokens for full file_tree context (project analyzer gets more)
ANALYZER_TOKEN_BUDGET = 12000


def classify_input(
    code: Optional[str] = None,
    file_tree: Optional[dict] = None,
    entry_point: Optional[str] = None,
    language: Optional[str] = "auto"
) -> dict:
    """
    Classifies and normalizes any input into a standard dict.
    """

    # ── Case 1: Pure snippet / error message ──────────────────────────────
    if code and not file_tree:
        lang = language if language and language != "auto" else detect_language_from_snippet(code)
        fname = f"snippet.{lang_to_ext(lang)}"
        return {
            "input_type": "snippet",
            "file_tree": {fname: code},
            "raw_input": code,
            "entry_point": fname,
            "language": lang,
            "total_tokens_estimate": estimate_tokens(code),
            "primary_file": fname,
        }

    # ── Case 2: Single file ───────────────────────────────────────────────
    if file_tree and len(file_tree) == 1:
        fname, content = next(iter(file_tree.items()))
        lang = language if language and language != "auto" else detect_language_from_filename(fname)
        return {
            "input_type": "file",
            "file_tree": file_tree,
            "raw_input": content,
            "entry_point": entry_point or fname,
            "language": lang,
            "total_tokens_estimate": estimate_tokens(content),
            "primary_file": fname,
        }

    # ── Case 3: Multi-file repo ───────────────────────────────────────────
    if file_tree and len(file_tree) > 1:
        # Filter out junk files
        clean_tree = filter_file_tree(file_tree)
        lang = language if language and language != "auto" else detect_language_from_tree(clean_tree)
        ep = entry_point or detect_entry_point(clean_tree, lang)
        total_tokens = sum(estimate_tokens(c) for c in clean_tree.values())

        return {
            "input_type": "repo",
            "file_tree": clean_tree,
            "raw_input": None,
            "entry_point": ep,
            "language": lang,
            "total_tokens_estimate": total_tokens,
            "primary_file": ep,
        }

    # ── Fallback ──────────────────────────────────────────────────────────
    return {
        "input_type": "snippet",
        "file_tree": {"input.txt": code or ""},
        "raw_input": code or "",
        "entry_point": "input.txt",
        "language": "unknown",
        "total_tokens_estimate": estimate_tokens(code or ""),
        "primary_file": "input.txt",
    }


def filter_file_tree(file_tree: dict) -> dict:
    """Remove binary, lock, and irrelevant files."""
    clean = {}
    for fname, content in file_tree.items():
        filename = os.path.basename(fname)
        ext = Path(fname).suffix.lower()

        if filename in SKIP_FILENAMES:
            continue
        if ext in SKIP_EXTENSIONS:
            continue
        if not content or not content.strip():
            continue
        # Skip very large single files (> 800 lines) — truncate them
        lines = content.splitlines()
        if len(lines) > 800:
            content = "\n".join(lines[:800]) + f"\n... [truncated {len(lines)-800} lines]"

        clean[fname] = content
    return clean


def detect_language_from_snippet(code: str) -> str:
    """Heuristic language detection from raw snippet."""
    code_lower = code.lower()
    if "def " in code and ("import " in code or "print(" in code):
        return "python"
    if "function " in code or "const " in code or "let " in code or "var " in code:
        return "javascript"
    if "public class " in code or "System.out" in code:
        return "java"
    if "#include" in code:
        return "cpp"
    if "func " in code and "fmt." in code:
        return "go"
    if "<?php" in code:
        return "php"
    if "def " in code and "end" in code:
        return "ruby"
    # If it looks like an error message not code
    if any(kw in code for kw in ["Error:", "Exception", "Traceback", "at line", "undefined"]):
        return "unknown"
    return "python"  # default


def detect_language_from_filename(fname: str) -> str:
    ext = Path(fname).suffix.lower()
    mapping = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".jsx": "javascript", ".tsx": "typescript", ".rb": "ruby",
        ".go": "go", ".java": "java", ".cpp": "cpp", ".c": "c",
        ".cs": "csharp", ".php": "php", ".rs": "rust", ".swift": "swift",
        ".kt": "kotlin", ".sh": "bash",
    }
    return mapping.get(ext, "unknown")


def detect_language_from_tree(file_tree: dict) -> str:
    """Pick most common language in the file tree."""
    counts = {}
    for fname in file_tree:
        lang = detect_language_from_filename(fname)
        if lang != "unknown":
            counts[lang] = counts.get(lang, 0) + 1
    return max(counts, key=counts.get) if counts else "python"


def detect_entry_point(file_tree: dict, language: str) -> str:
    """Detect the most likely entry point for a given language."""
    candidates = {
        "python":     ["main.py", "app.py", "run.py", "server.py", "manage.py", "index.py"],
        "javascript": ["index.js", "main.js", "app.js", "server.js", "src/index.js"],
        "typescript": ["index.ts", "main.ts", "app.ts", "src/index.ts"],
        "go":         ["main.go", "cmd/main.go"],
        "ruby":       ["main.rb", "app.rb", "config.ru"],
        "java":       ["Main.java", "App.java", "Application.java"],
    }
    for candidate in candidates.get(language, []):
        if candidate in file_tree:
            return candidate
    # Fallback: first .py / .js file
    for fname in file_tree:
        if fname.endswith((".py", ".js", ".ts")):
            return fname
    return list(file_tree.keys())[0]


def lang_to_ext(lang: str) -> str:
    mapping = {
        "python": "py", "javascript": "js", "typescript": "ts",
        "ruby": "rb", "go": "go", "java": "java", "cpp": "cpp",
        "csharp": "cs", "php": "php", "rust": "rs",
    }
    return mapping.get(lang.lower(), "txt")


def build_focused_context(
    classified: dict,
    run_result: dict,
    project_info: dict,
    token_budget: int = AGENT_TOKEN_BUDGET
) -> str:
    """
    Builds the smartest possible context string within a token budget.

    Priority order:
      1. Execution output (stderr/stdout) — always included first
      2. Primary / entry point file — always included
      3. Files referenced in the error — included next
      4. Other files — included until budget exhausted
    """
    parts = []
    tokens_used = 0

    # ── 1. Project overview (always, compact) ─────────────────────────────
    overview = (
        f"PROJECT: {project_info.get('summary', 'Unknown')}\n"
        f"Language: {project_info.get('language', 'Unknown')} | "
        f"Framework: {project_info.get('framework', 'None')} | "
        f"Entry: {classified.get('entry_point', 'Unknown')}\n"
    )
    parts.append(overview)
    tokens_used += estimate_tokens(overview)

    # ── 2. Execution output (always, capped at 1500 tokens) ───────────────
    stderr = run_result.get("stderr", "").strip()
    stdout = run_result.get("stdout", "").strip()
    runner_err = run_result.get("error", "")

    exec_parts = []
    if stderr:
        exec_parts.append(f"[STDERR]\n{stderr[:4000]}")
    if stdout:
        exec_parts.append(f"[STDOUT]\n{stdout[:2000]}")
    if runner_err:
        exec_parts.append(f"[RUNNER ERROR]\n{runner_err}")
    exec_parts.append(f"[EXIT CODE] {run_result.get('exit_code', -1)}")

    exec_block = "\n".join(exec_parts)
    # Cap execution output to 1500 tokens
    exec_block = truncate_to_tokens(exec_block, 1500)
    parts.append(exec_block)
    tokens_used += estimate_tokens(exec_block)

    # ── 3. Primary/entry-point file ───────────────────────────────────────
    file_tree = classified.get("file_tree", {})
    primary = classified.get("entry_point") or classified.get("primary_file")

    remaining = token_budget - tokens_used
    if primary and primary in file_tree:
        block = f"\n--- {primary} (entry point) ---\n{file_tree[primary]}"
        block = truncate_to_tokens(block, min(remaining, 2500))
        parts.append(block)
        tokens_used += estimate_tokens(block)

    # ── 4. Files mentioned in stderr ─────────────────────────────────────
    mentioned = extract_mentioned_files(stderr, file_tree)
    for fname in mentioned:
        if fname == primary:
            continue
        remaining = token_budget - tokens_used
        if remaining < 200:
            break
        block = f"\n--- {fname} ---\n{file_tree[fname]}"
        block = truncate_to_tokens(block, min(remaining, 1500))
        parts.append(block)
        tokens_used += estimate_tokens(block)

    # ── 5. Remaining files until budget ───────────────────────────────────
    for fname, content in file_tree.items():
        if fname == primary or fname in mentioned:
            continue
        remaining = token_budget - tokens_used
        if remaining < 200:
            parts.append(f"\n[{len(file_tree) - len(parts)} more files omitted — token budget reached]")
            break
        block = f"\n--- {fname} ---\n{content}"
        block = truncate_to_tokens(block, min(remaining, 1000))
        parts.append(block)
        tokens_used += estimate_tokens(block)

    return "\n".join(parts)


def extract_mentioned_files(stderr: str, file_tree: dict) -> list:
    """Find file_tree keys that appear in the error output."""
    mentioned = []
    for fname in file_tree:
        basename = os.path.basename(fname)
        if basename in stderr or fname in stderr:
            mentioned.append(fname)
    return mentioned


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated, {len(text) - max_chars} chars omitted]"
