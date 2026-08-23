"""LLM-as-judge for prose correctness ONLY.

Everything programmatically checkable (citations, escalation flag, override
flag, structured verdict fields) is scored in run_eval.py without a model call.
The judge exists for the one thing a substring cannot decide: is the answer
actually right and well explained against its rubric.

Deliberately uses get_judge_client(), never the answering model -- a model
grading its own output inflates the score.
"""

from __future__ import annotations

import json

from app.llm.client import get_judge_client

_SCHEMA = {
    "type": "object",
    "properties": {
        "meets_rubric": {"type": "boolean"},
        "reasoning": {"type": "string"},
    },
    "required": ["meets_rubric", "reasoning"],
}


def judge_answer(question: str, answer: str, rubric: str) -> dict:
    client = get_judge_client()
    prompt = (
        f"Question asked: {question}\n\n"
        f"Answer given: {answer}\n\n"
        f"Rubric (what the answer must do to be correct): {rubric}\n\n"
        f"Does the answer meet the rubric? Judge strictly -- a technically "
        f"correct number with a missing required caveat does NOT meet the "
        f"rubric. Respond as JSON."
    )
    try:
        resp = client.complete(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema",
                            "json_schema": {"schema": _SCHEMA}},
        )
        data = json.loads(resp.content or "{}")
        return {"meets_rubric": bool(data.get("meets_rubric")),
                "reasoning": data.get("reasoning", "")}
    except Exception as exc:  # noqa: BLE001
        return {"meets_rubric": None, "reasoning": f"judge unavailable: {exc}"}
