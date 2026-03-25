import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])


SYSTEM_PROMPT = """
You are an Error Line Identification Agent.

Your ONLY job:
1. Identify the exact line number where the error occurs
2. Extract the failing code snippet from that line

STRICT RULES:
- Output MUST be valid JSON
- NO explanations
- NO markdown
- ONLY one JSON object

Output format:
{
  "line": <line_number>,
  "snippet": "exact code causing error"
}

If line cannot be determined:
{
  "line": -1,
  "snippet": "Not found"
}
"""


def identify_error_line(input_text: str):
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
                    "content": f"Analyze the following code/logs and find the exact failing line:\n\n{input_text}"
                }
            ],
        )
        content = response.choices[0].message.content.strip()
        parsed = safe_json_parse(content)
        return normalize_output(parsed)
    except Exception as e:
        return {"line": -1, "snippet": f"AgentError: {str(e)}"}


def safe_json_parse(content: str):
    try:
        return json.loads(content)
    except:
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            return json.loads(content[start:end])
        except:
            return {"line": -1, "snippet": content}


def normalize_output(result: dict):
    return {
        "line": result.get("line", -1),
        "snippet": result.get("snippet", "Not found")
    }


def run_line_agent(input_text: str):
    return identify_error_line(input_text)


if __name__ == "__main__":
    test_input = """
    20 | const user = getUser();
    21 | console.log(user.name);
    22 | const data = user.profile.age;
    TypeError: Cannot read property 'profile' of undefined at line 22
    """
    result = run_line_agent(test_input)
    print(result)
