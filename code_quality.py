"""
Code Quality Agent
Performs holistic static analysis across all files in a project.
For repos, it understands the ENTIRE codebase as one connected system —
not individual files in isolation.

Returns:
  {
    "code_quality": "clean" | "warning" | "issues",
    "quality_summary": "One-line overall verdict",
    "quality_issues": [
      { "file": "filename", "issue": "description", "severity": "Low|Medium|High" }
    ]
  }
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))


SYSTEM_PROMPT = """
You are a Code Quality Review Agent.

Your job:
- Analyze the ENTIRE project/code as a connected system
- For multi-file projects, trace how files interact and import each other
- Identify real code quality issues, not just style nits

Focus on:
1. Logic bugs (incorrect conditions, off-by-one, missing edge cases)
2. Cross-file issues (broken imports, mismatched function signatures, missing exports)
3. Security risks (hardcoded secrets, unsafe eval, SQL injection patterns)
4. Null/undefined access on unguarded objects
5. Missing error handling for critical operations
6. Dead code or unreachable branches
7. Type mismatches across function calls

DO NOT report:
- Style preferences (spacing, naming conventions)
- Minor suggestions that don't affect correctness
- Issues already handled by existing try/except blocks

STRICT RULES:
- Output MUST be valid JSON only
- NO markdown, NO backticks, NO extra text
- quality_issues must be an array (empty [] if none)
- Limit to max 8 most important issues

Output format:
{
  "code_quality": "clean" | "warning" | "issues",
  "quality_summary": "One sentence overall assessment",
  "quality_issues": [
    {
      "file": "filename or 'cross-file'",
      "issue": "Specific description of the problem",
      "severity": "Low" | "Medium" | "High"
    }
  ]
}

Scoring:
- "clean"   → No meaningful issues found, code is correct and safe
- "warning" → Minor issues found, code likely works but has risks
- "issues"  → Real bugs or security problems that need fixing
"""


def analyze_code_quality(project_context: str) -> dict:
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            temperature=0,
            max_tokens=800,
            top_p=1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Review this entire project for code quality issues:\n\n{project_context}"
                }
            ]
        )
        content = response.choices[0].message.content.strip()
        parsed = safe_json_parse(content)
        return normalize_output(parsed)
    except Exception as e:
        return {
            "code_quality": "warning",
            "quality_summary": f"Quality check unavailable: {str(e)}",
            "quality_issues": []
        }


def safe_json_parse(content: str) -> dict:
    try:
        return json.loads(content)
    except Exception:
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            return json.loads(content[start:end])
        except Exception:
            return {
                "code_quality": "warning",
                "quality_summary": "Could not parse quality response",
                "quality_issues": []
            }


def normalize_output(result: dict) -> dict:
    quality = result.get("code_quality", "warning").lower()
    if quality not in ("clean", "warning", "issues"):
        quality = "warning"

    issues = result.get("quality_issues", [])
    # Ensure each issue has required fields
    normalized_issues = []
    for item in issues:
        if isinstance(item, dict):
            normalized_issues.append({
                "file":     item.get("file", "unknown"),
                "issue":    item.get("issue", "Unspecified issue"),
                "severity": item.get("severity", "Medium")
            })

    return {
        "code_quality":    quality,
        "quality_summary": result.get("quality_summary", "No summary available"),
        "quality_issues":  normalized_issues
    }


def run_code_quality_agent(project_context: str) -> dict:
    return analyze_code_quality(project_context)


if __name__ == "__main__":
    test_context = """
FILE: main.py
import pandas as pd

def process(df):
    result = df['nonexistent_column'].sum()
    return result

df = pd.DataFrame({'a': [1, 2, 3]})
print(process(df))

FILE: utils.py
def divide(a, b):
    return a / b   # No zero-division guard

def load_data(path):
    import pickle
    return pickle.load(open(path, 'rb'))  # Security: unsafe pickle + unclosed file handle
"""
    result = run_code_quality_agent(test_context)
    print(json.dumps(result, indent=2))