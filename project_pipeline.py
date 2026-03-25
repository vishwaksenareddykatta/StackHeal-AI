"""
Project Pipeline Orchestrator
Full flow:
  1. Analyze project structure
  2. Run the project
  3. If error → pass through all 7 agents with full context
  4. If no error → return clean success result
"""

import json
from project_analyzer import run_project_analyzer
from runner import run_project, build_execution_report, has_error

from error_detection import run_error_agent
from error_line import run_line_agent
from error_classify import run_classification_agent
from root_cause import run_root_cause_agent
from fix import run_fix_agent
from explain import run_explanation_agent
from confident import run_confidence_agent


NO_ERROR_RESULT = {
    "status": "success",
    "type": "NoError",
    "message": "No error detected",
    "line": -1,
    "snippet": "",
    "severity": "None",
    "root_cause": "",
    "description": "Project ran successfully with no errors.",
    "correctedCode": "",
    "simple": "Your project ran without any issues!",
    "detailed": "All files executed successfully. No errors, exceptions, or non-zero exit codes were detected.",
    "confidence": 1.0,
}


def run_project_pipeline(file_tree: dict, entry_point: str = None, language: str = "auto") -> dict:
    """
    Main entry point for full project analysis.

    Args:
        file_tree: { "filename": "file content", ... }
        entry_point: which file to run (auto-detected if None)
        language: programming language (auto-detected if "auto")

    Returns:
        Full structured result dict
    """
    result = {}

    # ── Step 1: Analyze project structure ──────────────────────────────────
    project_info = run_project_analyzer(file_tree)
    result["project"] = project_info

    # Auto-detect entry point if not provided
    if not entry_point:
        entry_point = project_info.get("entry_point", "main.py")

    # Auto-detect language
    if language == "auto":
        language = project_info.get("language", "Python").lower()

    # ── Step 2: Pre-run issue check ─────────────────────────────────────────
    pre_run_issues = project_info.get("pre_run_issues", [])
    if pre_run_issues and any(pre_run_issues):
        # There are potential issues even before running
        result["pre_run_issues"] = pre_run_issues

    # ── Step 3: Run the project ─────────────────────────────────────────────
    run_result = run_project(file_tree, entry_point, language)
    result["execution"] = {
        "ran": run_result["ran"],
        "exit_code": run_result["exit_code"],
        "stdout": run_result.get("stdout", ""),
        "stderr": run_result.get("stderr", ""),
        "install_output": run_result.get("install_output", ""),
    }

    # ── Step 4: Check if there's actually an error ──────────────────────────
    if not has_error(run_result) and not pre_run_issues:
        final = {**NO_ERROR_RESULT}
        final["project"] = project_info
        final["execution"] = result["execution"]
        final["language"] = project_info.get("language", "Unknown")
        final["framework"] = project_info.get("framework", "None")
        final["entry_point"] = entry_point
        final["summary"] = project_info.get("summary", "")
        return final

    # ── Step 5: Build rich context for agents ───────────────────────────────
    # Combine: project info + file contents + execution output
    project_context = build_agent_context(file_tree, project_info, run_result)

    # ── Step 6: Run all 7 agents with full context ──────────────────────────
    agent_result = {}

    error_info = run_error_agent(project_context)
    agent_result.update(error_info)

    line_info = run_line_agent(project_context)
    agent_result.update(line_info)

    classification = run_classification_agent(project_context)
    agent_result.update(classification)

    root_cause = run_root_cause_agent(project_context)
    agent_result.update(root_cause)

    fix_info = run_fix_agent(project_context)
    agent_result.update(fix_info)

    explanation = run_explanation_agent(project_context)
    agent_result.update(explanation)

    confidence = run_confidence_agent(agent_result)
    agent_result["confidence"] = confidence

    # ── Step 7: Merge everything ─────────────────────────────────────────────
    agent_result["status"] = "error"
    agent_result["project"] = project_info
    agent_result["execution"] = result["execution"]
    agent_result["language"] = project_info.get("language", classification.get("language", "Unknown"))
    agent_result["framework"] = project_info.get("framework", "None")
    agent_result["entry_point"] = entry_point
    agent_result["summary"] = project_info.get("summary", "")
    agent_result["pre_run_issues"] = pre_run_issues

    return agent_result


def build_agent_context(file_tree: dict, project_info: dict, run_result: dict) -> str:
    """
    Builds a single rich string combining:
    - Project summary
    - All file contents (with filenames as headers)
    - Execution output (stdout, stderr, errors)
    """
    parts = []

    # Project overview
    parts.append(f"""PROJECT OVERVIEW
Language: {project_info.get('language', 'Unknown')}
Framework: {project_info.get('framework', 'None')}
Entry Point: {project_info.get('entry_point', 'Unknown')}
Summary: {project_info.get('summary', '')}
Pre-run Issues: {', '.join(project_info.get('pre_run_issues', [])) or 'None'}
""")

    # All file contents
    parts.append("PROJECT FILES:")
    for filename, content in file_tree.items():
        parts.append(f"\n--- {filename} ---\n{content}")

    # Execution result
    parts.append("\nEXECUTION OUTPUT:")
    parts.append(build_execution_report(run_result))

    return "\n".join(parts)


if __name__ == "__main__":
    # Quick local test with a broken Python project
    sample_files = {
        "main.py": """
import pandas as pd
import numpy as np

df = pd.DataFrame({'a': [1, 2, 3]})
result = df['b'].sum()   # KeyError: 'b' doesn't exist
print(result)
""",
        "requirements.txt": "pandas==2.0.3\nnumpy==1.24.0"
    }

    result = run_project_pipeline(sample_files, entry_point="main.py", language="python")
    print("\n=== PROJECT PIPELINE RESULT ===\n")
    print(json.dumps(result, indent=2, default=str))
