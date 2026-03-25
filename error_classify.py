import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])


SYSTEM_PROMPT = """
You are an Error Classification Agent.

Your ONLY job:
1. Classify the error into a category
2. Assign severity level
3. Detect programming language

STRICT RULES:
- Output MUST be valid JSON
- NO explanations
- NO markdown
- ONLY one JSON object

Categories:
- Syntax Error
- Runtime Error
- Logical Error
- Dependency Error
- Configuration Error
- Unknown Error

Severity Levels:
- Low
- Medium
- High
- Critical

Output format:
{
  "type": "Error Category",
  "severity": "Severity Level",
  "language": "Programming Language"
}

If unknown:
{
  "type": "Unknown Error",
  "severity": "Medium",
  "language": "Unknown"
}
"""


def classify_error(input_text: str):
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            temperature=0,
            max_tokens=200,
            top_p=1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Analyze and classify the following error/code:\n\n{input_text}"
                }
            ],
        )
        content = response.choices[0].message.content.strip()
        parsed = safe_json_parse(content)
        return normalize_output(parsed)
    except Exception as e:
        return {
            "type": "Unknown Error",
            "severity": "Medium",
            "language": f"AgentError: {str(e)}"
        }


def safe_json_parse(content: str):
    try:
        return json.loads(content)
    except:
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            return json.loads(content[start:end])
        except:
            return {"type": "Unknown Error", "severity": "Medium", "language": "ParsingError"}


def normalize_output(result: dict):
    return {
        "type": result.get("type", "Unknown Error"),
        "severity": result.get("severity", "Medium"),
        "language": result.get("language", "Unknown")
    }


def run_classification_agent(input_text: str):
    return classify_error(input_text)


if __name__ == "__main__":
    test_inputs = [
        "TypeError: cannot read property 'map' of undefined",
        "SyntaxError: invalid syntax in Python file",
        "NullPointerException at line 42 in Java",
        "ModuleNotFoundError: No module named 'numpy'"
    ]
    for test in test_inputs:
        print("\nINPUT:", test)
        print("OUTPUT:", run_classification_agent(test))
