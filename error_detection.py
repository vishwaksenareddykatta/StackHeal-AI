import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])


SYSTEM_PROMPT = """
You are a strict Error Detection Agent.

Your ONLY job:
1. Detect if an error exists in the input
2. Identify the error type (e.g., TypeError, SyntaxError, NullPointerException, etc.)
3. Extract the exact error message

STRICT RULES:
- Output MUST be valid JSON
- NO markdown
- NO explanation
- NO extra text
- ONLY one JSON object

Output format:
{
  "type": "ErrorType",
  "message": "Exact error message"
}

If no error is found:
{
  "type": "NoError",
  "message": "No error detected"
}
"""


def detect_error(input_text: str):
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
                    "content": f"Analyze the following input and detect error:\n\n{input_text}"
                }
            ],
        )
        content = response.choices[0].message.content.strip()
        return safe_json_parse(content)
    except Exception as e:
        return {"type": "AgentError", "message": str(e)}


def safe_json_parse(content: str):
    try:
        return json.loads(content)
    except:
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            return json.loads(content[start:end])
        except:
            return {"type": "ParsingError", "message": content}


def run_error_agent(input_text: str):
    result = detect_error(input_text)
    return {
        "type": result.get("type", "UnknownError"),
        "message": result.get("message", "")
    }


if __name__ == "__main__":
    test_cases = [
        "TypeError: cannot read property 'map' of undefined",
        "NullPointerException at line 42",
        "SyntaxError: invalid syntax",
        "Everything executed successfully"
    ]
    for test in test_cases:
        print("\nINPUT:", test)
        print("OUTPUT:", run_error_agent(test))
