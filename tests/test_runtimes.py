import pytest

from band_agentd.config import DaemonConfig
from band_agentd.daemon import build_adapter
from band_agentd.runtimes import ModelOption, format_models, validate_choice

MODELS = [
    ModelOption("fast", "Fast", "quick work", False, ("low", "medium"), "low"),
    ModelOption("deep", "Deep", "hard work", True, ("low", "medium", "high", "max"), "medium"),
]


def test_valid_model_and_effort_pass():
    validate_choice(MODELS, "fast", "medium")
    validate_choice(MODELS, None, "max")
    validate_choice(MODELS, None, None)


def test_unknown_model_lists_the_choices():
    with pytest.raises(ValueError, match="fast, deep"):
        validate_choice(MODELS, "missing", None)


def test_effort_is_checked_against_the_chosen_model():
    with pytest.raises(ValueError, match="low, medium"):
        validate_choice(MODELS, "fast", "max")


def test_effort_without_model_is_checked_against_the_default():
    with pytest.raises(ValueError, match="deep"):
        validate_choice(MODELS, None, "ultra")


def test_listing_marks_the_default_and_its_reasoning_levels():
    text = format_models("codex", MODELS)

    assert "* deep  reasoning: low medium high max (default medium)" in text
    assert "  fast  reasoning: low medium (default low)" in text


@pytest.mark.parametrize(
    ("adapter", "field"),
    [("codex", "reasoning_effort"), ("claude", "effort")],
)
def test_model_and_reasoning_reach_the_runtime(tmp_path, adapter, field):
    config = DaemonConfig.model_validate(
        {
            "runtime": {
                "adapter": adapter,
                "cwd": str(tmp_path),
                "model": "deep",
                "reasoning_effort": "high",
            }
        }
    )

    adapter_config = build_adapter(config).config

    assert adapter_config.model == "deep"
    assert getattr(adapter_config, field) == "high"
