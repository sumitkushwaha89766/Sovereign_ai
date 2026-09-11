import pytest

from app.agent.planner import PlannerParseError, _parse_json_response, _parse_reason_response


def test_invalid_vision_json_is_fatal():
    with pytest.raises(PlannerParseError, match="invalid JSON"):
        _parse_json_response("not json")


def test_empty_vision_json_is_fatal():
    with pytest.raises(PlannerParseError):
        _parse_json_response("{}")


def test_reasoning_response_requires_all_sections():
    with pytest.raises(PlannerParseError, match="required sections"):
        _parse_reason_response("BACKGROUND: context")


def test_reasoning_response_parses_all_sections():
    result = _parse_reason_response(
        "BACKGROUND: context\n"
        "RISK_ASSESSMENT: low risk\n"
        "CONDITIONS: - monitor every 4 hours\n"
        "RECOMMENDATION: continue under conditions"
    )

    assert result["background"] == "context"
    assert result["conditions"] == ["monitor every 4 hours"]
