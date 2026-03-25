import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# 🔑 Initialize client
client = Groq(api_key=os.environ["GROQ_API_KEY"])


SYSTEM_PROMPT = """
You are a Confidence Scoring Agent.

Your ONLY job:
- Analyze the given debugging result
- Output a confidence score between 0 and 1

STRICT RULES:
- Output MUST be ONLY a number
- NO JSON
- NO explanation
- NO text
- Example: 0.87

Scoring Guidelines:
- 0.9 - 1.0 → Very clear error, precise fix
- 0.7 - 0.89 → Good confidence, minor ambiguity
- 0.5 - 0.69 → Moderate confidence
- 0.3 - 0.49 → Low confidence
- 0.0 - 0.29 → Very uncertain
"""


def get_confidence(input_text: str):
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            temperature=0,
            max_tokens=10,
            top_p=1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Evaluate confidence for this debugging result:\n\n{input_text}"
                }
            ]
        )
        content = response.choices[0].message.content.strip()
        return normalize_score(content)
    except Exception:
        return 0.5


def normalize_score(content: str):
    try:
        score = float(content)
        if score < 0:
            return 0.0
        elif score > 1:
            return 1.0
        else:
            return round(score, 2)
    except:
        return 0.5


def calculate_dynamic_confidence(full_result: dict) -> float:
    """
    Calculate confidence score based on error characteristics.
    Provides intelligent scoring even when API calls fail.
    """
    score = 0.5  # Base score
    
    # Severity-based adjustments
    severity = full_result.get("severity", "").lower()
    if severity == "critical":
        score += 0.15  # High confidence for critical errors (clear issues)
    elif severity == "high":
        score += 0.12
    elif severity == "medium":
        score += 0.05
    elif severity == "low":
        score -= 0.10  # Lower confidence for low-severity issues
    
    # Root cause clarity
    root_cause = str(full_result.get("root_cause", "")).strip()
    if root_cause and len(root_cause) > 20:
        score += 0.10  # Good explanation boost
    
    # Code snippet quality
    snippet = str(full_result.get("snippet", "")).strip()
    corrected = str(full_result.get("correctedCode", "")).strip()
    
    if snippet and corrected:
        score += 0.08  # Both provided
    
    # Error type detection (common, clear errors = higher confidence)
    error_type = full_result.get("type", "").lower()
    clear_errors = [
        "type error", "syntax error", "reference error", 
        "undefined", "null pointer", "attribute error",
        "index error", "key error", "import error"
    ]
    
    if any(e in error_type for e in clear_errors):
        score += 0.15
    elif "runtime error" in error_type or "logic error" in error_type:
        score += 0.05
    
    # Message clarity (longer, detailed messages = better understanding)
    message = str(full_result.get("message", "")).strip()
    if message and len(message) > 30:
        score += 0.08
    
    # Language experience boost (some languages more predictable than others)
    language = full_result.get("language", "").lower()
    predictable_langs = ["python", "javascript", "typescript", "java"]
    if any(lang in language for lang in predictable_langs):
        score += 0.05
    
    # Detailed explanation quality
    detailed = str(full_result.get("detailed", "")).strip()
    if detailed and len(detailed) > 50:
        score += 0.10
    
    # Description quality
    description = str(full_result.get("description", "")).strip()
    if description and len(description) > 30:
        score += 0.07
    
    # Clamp to [0, 1] range
    return max(0.0, min(1.0, round(score, 2)))


def run_confidence_agent(full_result: dict):
    """
    Calculate confidence score using AI + dynamic fallback.
    Always returns a dynamic score, never static 0.5.
    """
    input_text = str(full_result)
    
    # Try AI-based scoring first
    try:
        api_score = get_confidence(input_text)
        # Only use API score if it's different from the error handler default
        if api_score != 0.5:
            return api_score
    except:
        pass
    
    # Fall back to dynamic calculation based on error characteristics
    dynamic_score = calculate_dynamic_confidence(full_result)
    return dynamic_score


if __name__ == "__main__":
    # Test with high-confidence error
    high_conf_result = {
        "type": "TypeError",
        "message": "Cannot read property 'map' of undefined - object is null before method call",
        "line": 22,
        "snippet": "user.profile.age",
        "severity": "High",
        "language": "JavaScript",
        "root_cause": "The 'user' object is null or undefined before accessing its properties. This typically occurs when data hasn't been fetched or initialized.",
        "description": "Add null/undefined check before accessing nested properties to prevent runtime errors.",
        "correctedCode": "if (user && user.profile) { const data = user.profile.age; } else { console.log('User not loaded'); }",
        "simple": "Check if the object exists before using it.",
        "detailed": "JavaScript cannot access properties of null or undefined values. Always verify objects exist before accessing their properties using && operator or optional chaining (?.)."
    }
    
    # Test with low-confidence error
    low_conf_result = {
        "type": "Logic Error",
        "message": "Unexpected behavior",
        "line": 0,
        "snippet": "",
        "severity": "Low",
        "language": "Python",
        "root_cause": "Something went wrong",
        "description": "Review the code",
        "correctedCode": "",
        "simple": "Fix it",
        "detailed": ""
    }
    
    print("🟢 High-confidence error score:", run_confidence_agent(high_conf_result))
    print("🔴 Low-confidence error score:", run_confidence_agent(low_conf_result))
