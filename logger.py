"""
Logger Module — StackHeal AI
Logs every analysis request and result to JSON log files.

Logs are written to ./logs/
  stackheal_YYYY-MM-DD.json  — one file per day, each line is a JSON record

Usage:
    from logger import log_analysis

    log_analysis(
        input_summary="dummyclient.py",
        input_type="file",
        result=pipeline_result,
        duration_ms=1240
    )
"""

import json
import os
import time
import threading
import traceback
from datetime import datetime, timezone
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
LOG_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
MAX_LOG_DAYS = 30        # keep at most 30 daily log files
_lock        = threading.Lock()

os.makedirs(LOG_DIR, exist_ok=True)


# ── Public API ────────────────────────────────────────────────────────────────

def log_analysis(
    input_summary: str,
    input_type: str,
    result: dict,
    duration_ms: int = 0,
    cache_hit: bool = False,
    extra: Optional[dict] = None,
) -> str:
    """
    Write one log entry for a completed analysis.

    Returns the log file path written to.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    ts_str   = now.isoformat()

    record = {
        "timestamp":      ts_str,
        "date":           date_str,
        "duration_ms":    duration_ms,
        "cache_hit":      cache_hit,

        # Input
        "input_type":     input_type,
        "input_summary":  input_summary[:300],   # cap to avoid huge logs

        # Core outputs
        "status":         result.get("status", "unknown"),
        "error_type":     result.get("type", ""),
        "error_message":  result.get("message", "")[:200],
        "severity":       result.get("severity", ""),
        "language":       result.get("language", ""),
        "line":           result.get("line", -1),
        "confidence":     result.get("confidence", 0.0),

        # Code quality
        "code_quality":       result.get("code_quality", ""),
        "quality_summary":    result.get("quality_summary", "")[:200],
        "quality_issue_count": len(result.get("quality_issues", [])),

        # Fix info
        "root_cause":     result.get("root_cause", "")[:200],
        "description":    result.get("description", "")[:200],
        "has_fix":        bool(result.get("correctedCode", "").strip()),

        # Execution
        "exit_code":      result.get("exit_code", -1),
        "ran":            result.get("execution", {}).get("ran", False),

        # Detection source
        "detection_source": result.get("detection_source", "ai"),   # "ai" | "dataset" | "cache"

        # Optional extra fields
        **(extra or {}),
    }

    log_path = os.path.join(LOG_DIR, f"stackheal_{date_str}.json")

    try:
        with _lock:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Logger] Failed to write log: {e}")

    # Rotate old logs (non-blocking, best-effort)
    threading.Thread(target=_rotate_old_logs, daemon=True).start()

    return log_path


def log_error(context: str, exception: Exception) -> None:
    """Log a pipeline-level exception to a separate error log."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    record = {
        "timestamp": now.isoformat(),
        "context":   context,
        "error":     str(exception),
        "traceback": traceback.format_exc(),
    }

    err_path = os.path.join(LOG_DIR, f"stackheal_errors_{date_str}.json")
    try:
        with _lock:
            with open(err_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_logs(date: Optional[str] = None, limit: int = 100) -> list:
    """
    Read log entries.

    date:  "YYYY-MM-DD" — read that day's log. Defaults to today.
    limit: max records to return (most recent first)
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log_path = os.path.join(LOG_DIR, f"stackheal_{date}.json")
    if not os.path.exists(log_path):
        return []

    records = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return []

    # Return most recent first, capped at limit
    return list(reversed(records))[:limit]


def log_stats(date: Optional[str] = None) -> dict:
    """
    Return summary statistics for a given day's logs.
    """
    records = read_logs(date=date, limit=10000)
    if not records:
        return {"total": 0, "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d")}

    total         = len(records)
    errors        = sum(1 for r in records if r.get("status") == "error")
    successes     = sum(1 for r in records if r.get("status") == "success")
    cache_hits    = sum(1 for r in records if r.get("cache_hit"))
    dataset_hits  = sum(1 for r in records if r.get("detection_source") == "dataset")
    ai_hits       = sum(1 for r in records if r.get("detection_source") == "ai")

    durations     = [r["duration_ms"] for r in records if r.get("duration_ms", 0) > 0]
    avg_ms        = int(sum(durations) / len(durations)) if durations else 0
    max_ms        = max(durations) if durations else 0

    error_types   = {}
    for r in records:
        t = r.get("error_type", "")
        if t and t not in ("NoError", ""):
            error_types[t] = error_types.get(t, 0) + 1

    top_errors = sorted(error_types.items(), key=lambda x: -x[1])[:10]

    return {
        "date":           date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total":          total,
        "errors":         errors,
        "successes":      successes,
        "cache_hits":     cache_hits,
        "dataset_hits":   dataset_hits,
        "ai_hits":        ai_hits,
        "avg_duration_ms": avg_ms,
        "max_duration_ms": max_ms,
        "top_errors":     [{"type": t, "count": c} for t, c in top_errors],
    }


# ── Internal ──────────────────────────────────────────────────────────────────

def _rotate_old_logs():
    """Delete log files older than MAX_LOG_DAYS."""
    try:
        files = sorted([
            f for f in os.listdir(LOG_DIR)
            if f.startswith("stackheal_") and f.endswith(".json")
        ])
        while len(files) > MAX_LOG_DAYS:
            oldest = files.pop(0)
            try:
                os.remove(os.path.join(LOG_DIR, oldest))
            except Exception:
                pass
    except Exception:
        pass
