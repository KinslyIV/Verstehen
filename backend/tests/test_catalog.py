import pytest
from pydantic_ai.settings import ThinkingEffort

from verstehen.providers.catalog import default_thinking_level


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        (["max", "xhigh", "minimal", "high", "low", "medium"], "medium"),
        (["max", "xhigh", "minimal", "high", "low"], "low"),
        (["max", "xhigh", "minimal", "high"], "high"),
        (["max", "xhigh", "minimal"], "minimal"),
        (["max", "xhigh"], "xhigh"),
        (["max"], "max"),
        ([], None),
    ],
)
def test_default_thinking_uses_first_supported_level_in_learnharness_order(
    levels: list[ThinkingEffort], expected: ThinkingEffort | None
):
    assert default_thinking_level(levels) == expected
