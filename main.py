"""
StackHeal AI — FastAPI Backend  v7.0.0
Run: uvicorn main:app --reload --port 8000

Endpoints:
  POST /analyze          — universal analysis (snippet / file / repo)
  GET  /health           — service health
  POST /cache/clear      — wipe all cached results
  GET  /cache/stats      — cache size and location
  GET  /logs             — today's analysis log (last 100 entries)
  GET  /logs/stats       — today's stats (total, errors, avg duration, top errors)
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, List
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from unified_pipeline import run_unified_pipeline
from cache import clear_cache, cache_stats
from logger import read_logs, log_stats

app = FastAPI(title="StackHeal AI", version="7.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response models ────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    code:        Optional[str]            = None
    file_tree:   Optional[Dict[str, str]] = None
    entry_point: Optional[str]            = None
    language:    Optional[str]            = "auto"


class QualityIssue(BaseModel):
    file:     str
    issue:    str
    severity: str


class AnalyzeResponse(BaseModel):
    status:       str
    input_type:   str

    code_quality:    str
    quality_summary: str
    quality_issues:  List[QualityIssue]

    type:          str
    message:       str
    line:          int
    snippet:       str
    severity:      str
    language:      str
    root_cause:    str
    description:   str
    correctedCode: str

    simple:       str
    detailed:     str
    confidence:   float

    # Detection source: "dataset" | "ai" | "cache" | "none"
    detection_source: Optional[str] = "ai"

    framework:      Optional[str]        = None
    entry_point:    Optional[str]        = None
    summary:        Optional[str]        = None
    pre_run_issues: Optional[List[str]]  = []

    stdout:    Optional[str] = ""
    stderr:    Optional[str] = ""
    exit_code: Optional[int] = -1


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status":  "ok",
        "service": "StackHeal AI",
        "version": "7.0.0",
        "modes":   ["snippet", "file", "repo"],
        "features": [
            "dataset pre-detection for all Python errors (no AI needed for known errors)",
            "parallel agent execution (6x faster)",
            "MD5 response cache (instant on repeat inputs)",
            "full JSON request logging",
            "cross-file repo analysis",
            "7-agent diagnostic pipeline",
        ],
    }


@app.post("/cache/clear")
def cache_clear():
    """Wipe all cached analysis results. Forces fresh analysis on next request."""
    deleted = clear_cache()
    return {"status": "ok", "entries_deleted": deleted}


@app.get("/cache/stats")
def cache_info():
    """Return current cache size and location."""
    return cache_stats()


@app.get("/logs")
def get_logs(
    date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
    limit: int = Query(100, description="Max records to return"),
):
    """Return recent analysis log entries (most recent first)."""
    return {"logs": read_logs(date=date, limit=limit)}


@app.get("/logs/stats")
def get_log_stats(
    date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Return summary stats for the day — total requests, error rate, top errors, avg speed."""
    return log_stats(date=date)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(body: AnalyzeRequest):
    """
    Universal analysis endpoint.
    Known Python errors are resolved from the local dataset instantly (no AI call).
    All other errors go through 7 parallel AI agents.
    """
    if not body.code and not body.file_tree:
        raise HTTPException(
            status_code=400,
            detail=(
                "Request must include at least one of:\n"
                "  'code'      — a code snippet or error message\n"
                "  'file_tree' — a dict of { filename: content }"
            ),
        )

    if body.file_tree and not any(v.strip() for v in body.file_tree.values()):
        raise HTTPException(
            status_code=400,
            detail="file_tree was provided but all file contents are empty.",
        )

    if body.code is not None and not body.code.strip():
        raise HTTPException(
            status_code=400,
            detail="'code' field was provided but is empty or whitespace only.",
        )

    try:
        result = run_unified_pipeline(
            code=body.code,
            file_tree=body.file_tree,
            entry_point=body.entry_point,
            language=body.language or "auto",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(exc)}")

    raw_issues = result.get("quality_issues", [])
    quality_issues = [
        QualityIssue(
            file=i.get("file", "unknown"),
            issue=i.get("issue", ""),
            severity=i.get("severity", "Medium"),
        )
        for i in raw_issues if isinstance(i, dict)
    ]

    return AnalyzeResponse(
        status=          result.get("status",        "error"),
        input_type=      result.get("input_type",    "snippet"),

        code_quality=    result.get("code_quality",    "warning"),
        quality_summary= result.get("quality_summary", ""),
        quality_issues=  quality_issues,

        type=            result.get("type",          "UnknownError"),
        message=         result.get("message",       ""),
        line=            result.get("line",          -1),
        snippet=         result.get("snippet",       ""),
        severity=        result.get("severity",      "Medium"),
        language=        result.get("language",      "Unknown"),
        root_cause=      result.get("root_cause",    ""),
        description=     result.get("description",   ""),
        correctedCode=   result.get("correctedCode", ""),

        simple=          result.get("simple",        ""),
        detailed=        result.get("detailed",      ""),
        confidence=      result.get("confidence",    0.5),

        detection_source= result.get("detection_source", "ai"),

        framework=       result.get("framework"),
        entry_point=     result.get("entry_point"),
        summary=         result.get("summary"),
        pre_run_issues=  result.get("pre_run_issues", []),

        stdout=          result.get("stdout",        ""),
        stderr=          result.get("stderr",        ""),
        exit_code=       result.get("exit_code",     -1),
    )
