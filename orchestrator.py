from error_detection import run_error_agent
from error_line import run_line_agent
from error_classify import run_classification_agent
from root_cause import run_root_cause_agent
from fix import run_fix_agent
from explain import run_explanation_agent
from confident import run_confidence_agent


def run_stackheal_pipeline(input_text: str):
    """
    Orchestrator for StackHeal AI pipeline.
    Runs all 7 agents in order and returns combined structured output.
    """
    final_result = {}

    # 1️⃣ Detect error
    error_result = run_error_agent(input_text)
    final_result.update(error_result)

    # 2️⃣ Identify error line
    line_result = run_line_agent(input_text)
    final_result.update(line_result)

    # 3️⃣ Classify error
    classification_result = run_classification_agent(input_text)
    final_result.update(classification_result)

    # 4️⃣ Root cause analysis
    root_cause_result = run_root_cause_agent(input_text)
    final_result.update(root_cause_result)

    # 5️⃣ Suggest fix
    fix_result = run_fix_agent(input_text)
    final_result.update(fix_result)

    # 6️⃣ Explanation (simple + detailed)
    explanation_result = run_explanation_agent(input_text)
    final_result.update(explanation_result)

    # 7️⃣ Confidence score
    confidence_score = run_confidence_agent(final_result)
    final_result["confidence"] = confidence_score

    return final_result


if __name__ == "__main__":
    test_input = """
    const user = getUser();
    console.log(user.name);
    const data = user.profile.age;
    TypeError: Cannot read property 'profile' of undefined at line 22
    """
    result = run_stackheal_pipeline(test_input)
    print("\nFINAL STACKHEAL AI OUTPUT:\n")
    import json
    print(json.dumps(result, indent=2))
