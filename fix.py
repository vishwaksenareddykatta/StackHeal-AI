import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])


SYSTEM_PROMPT = """
You are a Fix Suggestion Agent.

Your ONLY job:
1. Suggest how to fix the error or improve the code
2. Provide a corrected code snippet

STRICT RULES:
- Output MUST be valid JSON and nothing else
- NO markdown, NO backticks, NO extra text before or after the JSON
- Keep description SHORT and actionable
- Code must be clean and minimal

Output format (return ONLY this, no wrapper):
{
  "description": "Short fix explanation",
  "correctedCode": "Fixed code snippet"
}

Guidelines:
- Prefer minimal fixes (do not rewrite entire code)
- Preserve original logic
- Add checks, corrections, or missing parts
- Make code language-appropriate
- If the input is code without an explicit error, identify the most likely bug and fix it
"""


def suggest_fix(input_text: str):
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            temperature=0.2,
            max_tokens=300,
            top_p=1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Analyze and fix the following code/error:\n\n{input_text}"
                }
            ]
            # ✅ No response_format — avoids 400 errors on ambiguous code inputs
        )
        content = response.choices[0].message.content.strip()
        parsed = safe_json_parse(content)
        return normalize_output(parsed)
    except Exception as e:
        return {"description": "Agent error occurred", "correctedCode": str(e)}


def safe_json_parse(content: str):
    try:
        return json.loads(content)
    except:
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            return json.loads(content[start:end])
        except:
            return {"description": "Parsing error", "correctedCode": content}


def normalize_output(result: dict):
    return {
        "description": result.get("description", "No fix suggested"),
        "correctedCode": result.get("correctedCode", "")
    }


def run_fix_agent(input_text: str):
    return suggest_fix(input_text)


if __name__ == "__main__":
    test_inputs = [
        "TypeError: cannot read property 'map' of undefined",
        """
        const user = getUser();
        console.log(user.name);
        const data = user.profile.age;
        """
    ]
    for test in test_inputs:
        print("\nINPUT:", test)
        print("OUTPUT:", run_fix_agent(test))
