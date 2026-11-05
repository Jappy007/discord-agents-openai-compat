"""Silence and reaction-only response contracts."""

from core.context_builder import SILENCE_INSTRUCTION
from tools.reaction_tools import REACT_TOOL
from tools.send_message import SEND_MESSAGE_TOOL, STAY_SILENT_TOOL


def test_stay_silent_tool_is_available_and_private_reason_is_optional():
    assert STAY_SILENT_TOOL["name"] == "stay_silent"
    assert STAY_SILENT_TOOL["input_schema"]["required"] == []
    assert "reason" in STAY_SILENT_TOOL["input_schema"]["properties"]
    assert "never posted" in STAY_SILENT_TOOL["description"].lower()


def test_send_message_points_silence_at_stay_silent():
    assert "stay_silent" in SEND_MESSAGE_TOOL["description"]


def test_reaction_is_a_complete_response():
    description = REACT_TOOL["description"]
    assert "complete response" in description
    assert "do not also post text" in description.lower()


def test_base_prompt_requires_stay_silent_instead_of_leaking_reasoning():
    assert "stay_silent" in SILENCE_INSTRUCTION
    assert "any text you output is posted" in SILENCE_INSTRUCTION
