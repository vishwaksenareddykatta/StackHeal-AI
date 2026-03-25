"""
Unified Pipeline  v8.0.0

Speed philosophy — EXECUTION IS THE GATE:
  ┌─────────────────────────────────────────────────────────────┐
  │  1. classify input  (local, ~0 ms)                         │
  │  2. pure error msg? ──yes──► dataset check ──hit──► return  │
  │          │                       │miss                      │
  │          │                       ▼                          │
  │         no                AI agents (parallel)              │
  │          │                                                  │
  │          ▼                                                  │
  │  3. RUN THE CODE ◄─── quality check runs in parallel        │
  │       │                                                     │
  │  exit_code=0 ──────────────────────────────► return clean   │
  │       │                                        (no AI)      │
  │  has stderr/error                                           │
  │       │                                                     │
  │  4. dataset check (instant) ────hit──────► return           │
  │       │ miss                                                │
  │  5. project_analyzer + 6 agents (parallel) ──► return       │
  └─────────────────────────────────────────────────────────────┘

What changed vs v7:
  • project_analyzer no longer blocks the happy path
  • Execution runs FIRST — if clean, zero AI calls are made
  • Quality check runs in parallel with execution (free on any path)
  • Error path: dataset match attempted BEFORE project_analyzer
  • project_analyzer only runs when there is a real error and dataset missed
  • project_analyzer + 6 agents now run concurrently (saves 1-2 s on cold errors)
"""

import json
import os
import time
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from input_classifier import (
    classify_input,
    build_focused_context,
    ANALYZER_TOKEN_BUDGET,
    AGENT_TOKEN_BUDGET,
    truncate_to_tokens,
    estimate_tokens,
)
from project_analyzer import run_project_analyzer
from runner import run_project, has_error
from code_quality import run_code_quality_agent

from error_detection import run_error_agent
from error_line import run_line_agent
from error_classify import run_classification_agent
from root_cause import run_root_cause_agent
from fix import run_fix_agent
from explain import run_explanation_agent
from confident import run_confidence_agent

from cache import make_key, get_cache, set_cache, clear_cache      # noqa: F401
from error_dataset import match_error as dataset_match_error
from logger import log_analysis, log_error


# ── Static templates ──────────────────────────────────────────────────────────

NO_ERROR_RESULT = {
    "status":        "success",
    "type":          "NoError",
    "message":       "No error detected. Project ran successfully.",
    "line":          -1,
    "snippet":       "",
    "severity":      "None",
    "root_cause":    "",
    "description":   "All files executed without errors.",
    "correctedCode": "",
    "simple":        "Your code ran without any issues!",
    "detailed":      "Execution completed with exit code 0. No exceptions or non-zero exit codes detected.",
    "confidence":    1.0,
    "detection_source": "none",
}

EXECUTABLE_LANGUAGES = {"python", "javascript", "typescript", "ruby", "go", "bash"}

SNIPPET_ONLY_HINTS = [
    "error:", "exception", "traceback", "at line", "undefined is not",
    "nullpointerexception", "segmentation fault", "syntaxerror",
    "typeerror", "valueerror", "keyerror", "indexerror",
    "modulenotfounderror", "importerror", "attributeerror",
    "zerodivisionerror", "nameerror", "filenotfounderror",
]


# ── Main entry point ──────────────────────────────────────────────────────────

def run_unified_pipeline(
    code: Optional[str] = None,
    file_tree: Optional[dict] = None,
    entry_point: Optional[str] = None,
    language: Optional[str] = "auto",
) -> dict:
    """
    Universal entry point — snippet, file, or full repo.
    Returns a full structured result dict.
    """
    start_time = time.monotonic()

    # ── Full-pipeline cache check ─────────────────────────────────────────────
    pipe_key = make_key(f"pipeline:{_input_fingerprint(code, file_tree, entry_point, language)}")
    cached = get_cache(pipe_key)
    if cached is not None:
        cached["detection_source"] = cached.get("detection_source", "cache")
        _do_log(cached, code, file_tree, start_time, cache_hit=True)
        return cached

    try:
        result = _run_pipeline(code, file_tree, entry_point, language)
        set_cache(pipe_key, result)
        _do_log(result, code, file_tree, start_time, cache_hit=False)
        return result
    except Exception as exc:
        log_error("run_unified_pipeline", exc)
        raise


def _run_pipeline(
    code: Optional[str],
    file_tree: Optional[dict],
    entry_point: Optional[str],
    language: Optional[str],
) -> dict:

    # ── 1. Classify input (local, ~0 ms) ─────────────────────────────────────
    classified = classify_input(
        code=code,
        file_tree=file_tree,
        entry_point=entry_point,
        language=language,
    )
    input_type = classified["input_type"]
    norm_tree  = classified["file_tree"]
    lang       = classified["language"]
    ep         = classified["entry_point"]

    # ── 2. Pure error message? Handle immediately — no execution needed ───────
    snippet_is_error = is_pure_error_message(code or "")
    if snippet_is_error:
        return _handle_pure_error_message(code, classified)

    # ── 3. Determine if we should execute ────────────────────────────────────
    should_run = (
        lang in EXECUTABLE_LANGUAGES
        and input_type in ("file", "repo", "snippet")
    )

    # ── 4. Run code + quality IN PARALLEL ────────────────────────────────────
    #   Quality runs alongside execution — zero extra wall-clock time.
    #   • If clean  → quality results are returned immediately with NO_ERROR_RESULT
    #   • If broken → quality results are already ready to attach to error response
    whole_project_context = _build_whole_project_context_local(norm_tree, classified)
    quality_key = make_key("code_quality:" + whole_project_context)

    def _run_quality():
        hit = get_cache(quality_key)
        if hit is not None:
            return hit
        r = run_code_quality_agent(whole_project_context)
        set_cache(quality_key, r)
        return r

    def _run_code():
        if should_run:
            return run_project(norm_tree, ep, lang)
        return {"stdout": "", "stderr": "", "exit_code": 0, "ran": False, "error": None}

    with ThreadPoolExecutor(max_workers=2) as pool:
        q_future = pool.submit(_run_quality)
        r_future = pool.submit(_run_code)
        quality_result = q_future.result()
        run_result     = r_future.result()

    # ── 5. CLEAN PATH — code ran with exit 0, zero AI calls ──────────────────
    if not has_error(run_result):
        result = {**NO_ERROR_RESULT}
        result.update(_common_fields_local(classified, run_result))
        result.update(quality_result)
        return result

    # ── 6. ERROR PATH — dataset check (instant, no API) ──────────────────────
    #   Terminal output (stderr) is the source of truth for error matching.
    error_text = (
        run_result.get("stderr", "")
        or run_result.get("error", "")
        or code or ""
    ).strip()

    dataset_result = dataset_match_error(error_text)
    if dataset_result:
        # Known error matched — skip ALL AI agents, return instantly
        dataset_result["status"] = "error"
        dataset_result.update(_common_fields_local(classified, run_result))
        dataset_result.update(quality_result)
        dataset_result["detection_source"] = "dataset"
        return dataset_result

    # ── 7. FULL AI PATH — project_analyzer + 6 agents run concurrently ───────
    return _run_full_ai_pipeline(classified, norm_tree, run_result, quality_result)


# ── Pure error message handler ────────────────────────────────────────────────

def _handle_pure_error_message(code: str, classified: dict) -> dict:
    """
    Input is a raw error string (no code to execute).
    Dataset check first — only falls through to AI if unrecognized.
    """
    run_result = {
        "stdout": "", "stderr": code or "",
        "exit_code": 1, "ran": False, "error": None,
        "install_output": "",
    }

    # Dataset check (instant)
    dataset_result = dataset_match_error(code or "")
    if dataset_result:
        dataset_result["status"] = "error"
        dataset_result.update(_common_fields_local(classified, run_result))
        dataset_result["detection_source"] = "dataset"
        dataset_result.setdefault("code_quality", "warning")
        dataset_result.setdefault("quality_summary", "No code provided for quality analysis")
        dataset_result.setdefault("quality_issues", [])
        return dataset_result

    # AI agents with just the error message as context
    minimal_project_info = {
        "language":       classified.get("language", "Unknown"),
        "framework":      "None",
        "entry_point":    classified.get("entry_point", ""),
        "project_type":   "Unknown",
        "dependencies":   [],
        "pre_run_issues": [],
        "summary":        "",
    }
    agent_context = build_focused_context(
        classified=classified,
        run_result=run_result,
        project_info=minimal_project_info,
        token_budget=AGENT_TOKEN_BUDGET,
    )
    agent_result = _run_all_agents_parallel(agent_context)
    agent_result["status"] = "error"
    agent_result.update(_common_fields_local(classified, run_result))
    agent_result.setdefault("code_quality", "warning")
    agent_result.setdefault("quality_summary", "No code provided for quality analysis")
    agent_result.setdefault("quality_issues", [])
    return agent_result


# ── Full AI pipeline (only reached when execution fails + dataset missed) ─────

def _run_full_ai_pipeline(
    classified: dict,
    norm_tree: dict,
    run_result: dict,
    quality_result: dict,
) -> dict:
    """
    Runs project_analyzer and all 6 diagnostic agents concurrently.

    If project_analyzer is cached → we have its output immediately and build
    a rich context before spawning agents (best quality).

    If not cached → project_analyzer and agents run in parallel using a lean
    context (stderr + code). This saves the full analyzer latency from the
    critical path while still delivering accurate fixes.
    """
    analyzer_tree = truncate_tree_for_analyzer(norm_tree, ANALYZER_TOKEN_BUDGET)
    analyzer_key  = make_key("project_analyzer:" + _tree_fingerprint(analyzer_tree))

    cached_project_info = get_cache(analyzer_key)

    if cached_project_info:
        # Cache hit — build rich context immediately, run agents
        project_info  = cached_project_info
        agent_context = build_focused_context(
            classified=classified,
            run_result=run_result,
            project_info=project_info,
            token_budget=AGENT_TOKEN_BUDGET,
        )
        agent_result = _run_all_agents_parallel(agent_context)

    else:
        # Cache miss — run analyzer + agents simultaneously
        # Agents get lean context (stderr + code) so they start immediately.
        # project_analyzer enriches language/framework metadata in the response.
        lean_context = _build_lean_context(classified, run_result)

        def _fetch_analyzer():
            info = run_project_analyzer(analyzer_tree)
            set_cache(analyzer_key, info)
            return info

        with ThreadPoolExecutor(max_workers=2) as pool:
            analyzer_future = pool.submit(_fetch_analyzer)
            agents_future   = pool.submit(_run_all_agents_parallel, lean_context)
            project_info = analyzer_future.result()
            agent_result = agents_future.result()

    pre_run_issues = project_info.get("pre_run_issues", [])
    agent_result["status"] = "error"
    agent_result.update(_common_fields_full(project_info, classified, run_result))
    agent_result.update(quality_result)
    agent_result["pre_run_issues"] = pre_run_issues
    return agent_result


# ── Parallel agent runner ─────────────────────────────────────────────────────

def _run_all_agents_parallel(context: str) -> dict:
    """
    Runs 6 diagnostic agents concurrently. Each result is cached independently.
    Confidence agent runs last (needs the merged result to score).
    """
    safe_ctx = truncate_to_tokens(context, AGENT_TOKEN_BUDGET)
    ctx_hash = make_key(safe_ctx)

    AGENTS = {
        "error":      (run_error_agent,          {"type": "UnknownError", "message": ""}),
        "line":       (run_line_agent,            {"line": -1, "snippet": ""}),
        "classify":   (run_classification_agent,  {"severity": "Medium", "language": "Unknown"}),
        "root_cause": (run_root_cause_agent,      {"root_cause": "Could not determine root cause"}),
        "fix":        (run_fix_agent,             {"description": "Fix unavailable", "correctedCode": ""}),
        "explain":    (run_explanation_agent,     {"simple": "An error occurred", "detailed": ""}),
    }

    result = {}

    def _run_cached(name: str, fn, fallback: dict):
        key = make_key(f"{name}:{ctx_hash}")
        hit = get_cache(key)
        if hit is not None:
            return hit
        try:
            out = fn(safe_ctx)
        except Exception:
            out = fallback
        set_cache(key, out)
        return out

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_run_cached, name, fn, fb): name
            for name, (fn, fb) in AGENTS.items()
        }
        for future in as_completed(futures):
            try:
                result.update(future.result())
            except Exception:
                pass

    # Confidence last — scores the full merged result
    conf_key = make_key(f"confidence:{json.dumps(result, sort_keys=True, default=str)}")
    conf = get_cache(conf_key)
    if conf is None:
        try:
            conf = run_confidence_agent(result)
        except Exception:
            conf = 0.5
        set_cache(conf_key, conf)
    result["confidence"] = conf
    result["detection_source"] = "ai"
    return result


# ── Context builders ──────────────────────────────────────────────────────────

def _build_lean_context(classified: dict, run_result: dict) -> str:
    """
    Fast context from stderr + code only — no AI call needed.
    Used when project_analyzer is running in parallel.
    """
    parts = []

    stderr     = run_result.get("stderr", "").strip()
    stdout     = run_result.get("stdout", "").strip()
    runner_err = run_result.get("error", "")

    if stderr:
        parts.append(f"[STDERR]\n{stderr[:3000]}")
    if stdout:
        parts.append(f"[STDOUT]\n{stdout[:1000]}")
    if runner_err:
        parts.append(f"[RUNNER ERROR]\n{runner_err}")
    parts.append(f"[EXIT CODE] {run_result.get('exit_code', -1)}")

    file_tree = classified.get("file_tree", {})
    primary   = classified.get("entry_point") or classified.get("primary_file")
    if primary and primary in file_tree:
        parts.append(f"\n--- {primary} ---\n{file_tree[primary][:4000]}")

    return "\n\n".join(parts)


def _build_whole_project_context_local(
    file_tree: dict,
    classified: dict,
    max_tokens: int = ANALYZER_TOKEN_BUDGET,
) -> str:
    """
    Builds the full project context using only local data (no AI call).
    Feeds the quality agent and acts as the quality cache key.
    """
    parts = []
    tokens_used = 0

    header = (
        f"=== PROJECT OVERVIEW ===\n"
        f"Input type : {classified.get('input_type', 'unknown').upper()}\n"
        f"Language   : {classified.get('language', 'Unknown')}\n"
        f"Entry point: {classified.get('entry_point', 'Unknown')}\n"
        f"{'='*50}\n\n"
        f"=== ALL PROJECT FILES ({len(file_tree)} total) ===\n\n"
    )
    parts.append(header)
    tokens_used += estimate_tokens(header)

    entry   = classified.get("entry_point", "")
    ordered = [(entry, file_tree[entry])] if entry and entry in file_tree else []
    for fname, content in file_tree.items():
        if fname != entry:
            ordered.append((fname, content))

    for fname, content in ordered:
        remaining = max_tokens - tokens_used
        if remaining < 150:
            break
        label = " ← ENTRY POINT" if fname == entry else ""
        block = f"--- FILE: {fname}{label} ---\n{content}\n"
        block = truncate_to_tokens(block, min(remaining, 2000))
        parts.append(block)
        tokens_used += estimate_tokens(block)

    return "\n".join(parts)


def _common_fields_local(classified: dict, run_result: dict) -> dict:
    """Common response fields using only local (classifier) information."""
    return {
        "input_type":  classified["input_type"],
        "language":    classified.get("language", "Unknown"),
        "framework":   "Unknown",
        "entry_point": classified.get("entry_point"),
        "summary":     "",
        "execution": {
            "ran":            run_result.get("ran", False),
            "exit_code":      run_result.get("exit_code", -1),
            "stdout":         run_result.get("stdout", ""),
            "stderr":         run_result.get("stderr", ""),
            "install_output": run_result.get("install_output", ""),
        },
        "stdout":    run_result.get("stdout", ""),
        "stderr":    run_result.get("stderr", ""),
        "exit_code": run_result.get("exit_code", -1),
    }


def _common_fields_full(project_info: dict, classified: dict, run_result: dict) -> dict:
    """Common response fields enriched with project_analyzer output."""
    return {
        "input_type":  classified["input_type"],
        "language":    project_info.get("language", classified.get("language", "Unknown")),
        "framework":   project_info.get("framework", "None"),
        "entry_point": classified.get("entry_point"),
        "summary":     project_info.get("summary", ""),
        "execution": {
            "ran":            run_result.get("ran", False),
            "exit_code":      run_result.get("exit_code", -1),
            "stdout":         run_result.get("stdout", ""),
            "stderr":         run_result.get("stderr", ""),
            "install_output": run_result.get("install_output", ""),
        },
        "stdout":    run_result.get("stdout", ""),
        "stderr":    run_result.get("stderr", ""),
        "exit_code": run_result.get("exit_code", -1),
    }


# ── Logging helper ────────────────────────────────────────────────────────────

def _do_log(result: dict, code, file_tree, start_time: float, cache_hit: bool):
    try:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        summary = (
            ", ".join(list(file_tree.keys())[:5]) if file_tree
            else (code[:80] if code else "unknown")
        )
        log_analysis(
            input_summary=summary,
            input_type=result.get("input_type", "unknown"),
            result=result,
            duration_ms=duration_ms,
            cache_hit=cache_hit,
        )
    except Exception:
        pass   # logging must never break the pipeline


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_pure_error_message(text: str) -> bool:
    if not text.strip():
        return False
    text_lower = text.lower()
    code_hints = ["def ", "function ", "class ", "import ", "const ", "let ", "var ", "public "]
    if any(h in text_lower for h in code_hints):
        return False
    return any(h in text_lower for h in SNIPPET_ONLY_HINTS)


def truncate_tree_for_analyzer(file_tree: dict, token_budget: int) -> dict:
    priority_names = {
        "requirements.txt", "package.json", "pyproject.toml", "go.mod",
        "Dockerfile", "docker-compose.yml", "setup.py", "setup.cfg",
        ".env.example", "README.md",
    }
    result      = {}
    tokens_used = 0

    for fname, content in file_tree.items():
        basename = os.path.basename(fname)
        if basename in priority_names:
            block = truncate_to_tokens(content, 500)
            tokens_used += estimate_tokens(block)
            result[fname] = block

    for fname, content in file_tree.items():
        if fname in result:
            continue
        remaining = token_budget - tokens_used
        if remaining < 300:
            break
        block = truncate_to_tokens(content, min(remaining, 1500))
        tokens_used += estimate_tokens(block)
        result[fname] = block

    return result


def _tree_fingerprint(file_tree: dict) -> str:
    items = sorted(f"{k}:{len(v)}" for k, v in file_tree.items())
    return "|".join(items)


def _input_fingerprint(code, file_tree, entry_point, language) -> str:
    parts = [
        code or "",
        json.dumps(sorted((file_tree or {}).items()), default=str),
        entry_point or "",
        language or "",
    ]
    return "|".join(parts)