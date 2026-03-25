"""
Project Analyzer Agent
Understands the full project structure, detects language/framework,
entry points, dependencies, and builds a rich context string for other agents.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))

SYSTEM_PROMPT = """
You are a Project Analysis Agent.

Your job:
1. Analyze the entire project file tree and file contents provided
2. Understand what the project does
3. Identify: language, framework, entry point, dependencies, project type
4. Spot any obvious issues BEFORE running (missing deps, wrong imports, config issues)

STRICT RULES:
- Output MUST be valid JSON only
- NO markdown, NO extra text

Output format:
{
  "language": "Python/JavaScript/TypeScript/etc",
  "framework": "FastAPI/React/Express/None/etc",
  "entry_point": "main.py / index.js / app.py / etc",
  "project_type": "Web API / CLI Tool / Library / Frontend App / etc",
  "dependencies": ["list", "of", "key", "deps"],
  "pre_run_issues": ["any obvious issues found before running"],
  "summary": "One line description of what this project does"
}
"""


def analyze_project(file_tree: dict) -> dict:
    """
    file_tree: { "filename": "file content", ... }
    Returns structured project analysis.
    """
    # Build a readable representation
    project_text = ""
    for filename, content in file_tree.items():
        project_text += f"\n\n{'='*40}\nFILE: {filename}\n{'='*40}\n{content}"

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            temperature=0,
            max_tokens=500,
            top_p=1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Analyze this project:\n{project_text}"
                }
            ]
        )
        content = response.choices[0].message.content.strip()
        return safe_json_parse(content)
    except Exception as e:
        return {
            "language": "Unknown",
            "framework": "Unknown",
            "entry_point": "Unknown",
            "project_type": "Unknown",
            "dependencies": [],
            "pre_run_issues": [f"Analysis failed: {str(e)}"],
            "summary": "Could not analyze project"
        }


def safe_json_parse(content: str) -> dict:
    try:
        return json.loads(content)
    except:
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            return json.loads(content[start:end])
        except:
            return {
                "language": "Unknown",
                "framework": "Unknown",
                "entry_point": "Unknown",
                "project_type": "Unknown",
                "dependencies": [],
                "pre_run_issues": ["Could not parse analysis response"],
                "summary": content[:200]
            }


def run_project_analyzer(file_tree: dict) -> dict:
    return analyze_project(file_tree)


if __name__ == "__main__":
    sample = {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/')\ndef root(): return {'hello': 'world'}",
        "requirements.txt": "fastapi==0.100.0\nuvicorn==0.23.0"
    }
    result = run_project_analyzer(sample)
    print(json.dumps(result, indent=2))
