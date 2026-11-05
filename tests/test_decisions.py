"""Unit tests for the Clef decision gate and the stay_silent tool."""

from types import SimpleNamespace

from core.context_builder import SILENCE_INSTRUCTION
from core.llm_providers.decisions import (
    ACTIONS,
    DEFAULT_REACTION_EMOJIS,
    _build_questions,
    _parse_decision,
)
from core.reactive_engine import ReactiveEngine
from tools.send_message import STAY_SILENT_TOOL, get_stay_silent_tool


def test_parse_choice_decision():
    payload = {
        "result": {
            "model": "clef",
            "answers": {
                "action": {
                    "type": "choice",
                    "choice": "reaction",
                    "probabilities": {"text": 0.1, "reaction": 0.7, "none": 0.2},
                    "confidence": 0.7,
                },
                "emoji": {
                    "type": "choice",
                    "choice": "👍",
                    "probabilities": {"👍": 0.6},
                    "confidence": 0.6,
                },
            },
        },
        "success": True,
    }

    decision = _parse_decision(payload)

    assert decision is not None
    assert decision.action == "reaction"
    assert decision.emoji == "👍"
    assert decision.confidence == 0.7
    assert decision.action_probabilities["reaction"] == 0.7
    assert decision.model == "clef"


def test_parse_bare_and_silent_decision():
    payload = {"answers": {"action": {"choice": "none", "confidence": 0.9}}}

    decision = _parse_decision(payload)

    assert decision is not None
    assert decision.action == "none"
    assert decision.should_respond is False


def test_parse_rejects_unknown_or_missing_action():
    assert _parse_decision({"result": {"answers": {"action": {"choice": "maybe"}}}}) is None
    assert _parse_decision({"result": {"answers": {}}}) is None
    assert _parse_decision({}) is None


def test_questions_cover_every_action_and_emoji():
    questions = _build_questions(DEFAULT_REACTION_EMOJIS)

    assert set(questions["action"]["criteria"]) == set(ACTIONS)
    assert set(questions["emoji"]["criteria"]) == set(DEFAULT_REACTION_EMOJIS)
    assert questions["action"]["type"] == "choice"
    assert questions["emoji"]["type"] == "choice"


def test_stay_silent_tool_shape():
    assert get_stay_silent_tool() is STAY_SILENT_TOOL
    assert STAY_SILENT_TOOL["name"] == "stay_silent"
    assert STAY_SILENT_TOOL["input_schema"]["required"] == []


def test_clef_prompt_disables_old_decision_path():
    engine = ReactiveEngine.__new__(ReactiveEngine)
    engine.discord_client = None
    context = {"system_prompt": f"base prompt\n{SILENCE_INSTRUCTION}\n"}

    prompt = engine._build_response_decision_prompt(context, clef_decided=True)[0]["text"]

    assert "Response Decision (Already Made)" in prompt
    assert "Response Decision Criteria" not in prompt
    assert SILENCE_INSTRUCTION not in prompt
    assert "Do not re-evaluate whether to respond" in prompt


def test_clef_text_turn_hides_decision_tools():
    engine = ReactiveEngine.__new__(ReactiveEngine)
    engine.discord_tool_executor = None
    engine.repository_manager = None
    engine.ask_prime_executor = None
    engine.web_search_enabled = False
    engine.mcp_manager = None
    engine.pptx_builder = object()
    engine.local_attachment_store = object()
    engine.config = SimpleNamespace(
        api=SimpleNamespace(model="test-model", context_tokens=8000)
    )

    params = engine._build_api_params(
        [{"type": "text", "text": "x"}], None, {"messages": []},
        decision_tools=False)
    names = {tool["name"] for tool in params["tools"]}

    assert "stay_silent" not in names
    assert "add_reaction" not in names
    assert "remove_reaction" not in names
    assert "send_message" in names
