import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])


SYSTEM_PROMPT = """
You are an Explanation Agent.

Your ONLY job:
- Convert technical errors into human-friendly explanations

You must return TWO formats:
1. Simple (for beginners)
2. Detailed (for developers)

STRICT RULES:
- Output MUST be valid JSON
- NO markdown
- NO extra text
- Simple = very short, easy to understand (1 line)
- Detailed = clear technical explanation (2-3 lines max)

Output format:
{
  "simple": "Beginner-friendly explanation",
  "detailed": "Technical explanation"
}
"""


def generate_explanation(input_text: str):
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            temperature=0.3,
            max_tokens=250,
            top_p=1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Explain the following error/code:\n\n{input_text}"
                }
            ],
        )
        content = response.choices[0].message.content.strip()
        parsed = safe_json_parse(content)
        return normalize_output(parsed)
    except Exception as e:
        return {"simple": "Unable to explain error", "detailed": f"AgentError: {str(e)}"}


def safe_json_parse(content: str):
    try:
        return json.loads(content)
    except:
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            return json.loads(content[start:end])
        except:
            return {"simple": content, "detailed": content}


def normalize_output(result: dict):
    return {
        "simple": result.get("simple", "No simple explanation available"),
        "detailed": result.get("detailed", "No detailed explanation available")
    }


def run_explanation_agent(input_text: str):
    return generate_explanation(input_text)


if __name__ == "__main__":
    test_inputs = [
        "TypeError: cannot read property 'map' of undefined",
        "NullPointerException at line 42",
        "SyntaxError: invalid syntax",
        "ModuleNotFoundError: No module named 'pandas'"
    ]
    for test in test_inputs:
        print("\nINPUT:", test)
        print("OUTPUT:", run_explanation_agent(test))
