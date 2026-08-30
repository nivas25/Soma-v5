from soma_data.config import (
    TEACHER_MAX_NEW_TOKENS,
    TEACHER_MODEL_FALLBACK,
    TEACHER_MODEL_PRIMARY,
    TEACHER_TEMPERATURE,
    TEACHER_TOP_P,
    teacher_model_candidates,
)


def test_teacher_is_transformers_not_vllm_awq():
    assert TEACHER_TEMPERATURE == 0.0
    assert TEACHER_TOP_P == 1.0
    assert TEACHER_MAX_NEW_TOKENS == 80
    assert "72B" not in TEACHER_MODEL_PRIMARY
    assert "AWQ" not in TEACHER_MODEL_PRIMARY
    assert TEACHER_MODEL_PRIMARY == "Qwen/Qwen2.5-32B-Instruct"
    assert TEACHER_MODEL_FALLBACK == "Qwen/Qwen2.5-14B-Instruct"


def test_80gb_picks_32b_else_14b():
    assert teacher_model_candidates(80) == [
        "Qwen/Qwen2.5-32B-Instruct",
        "Qwen/Qwen2.5-14B-Instruct",
    ]
    assert teacher_model_candidates(40) == ["Qwen/Qwen2.5-14B-Instruct"]
