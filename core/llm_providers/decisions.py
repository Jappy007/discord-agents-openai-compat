"""
Clef decision gate - cheap triage before a full model turn.

Logfare exposes Clef (and clef-flash) at POST /v1/decisions: instead of
generating text, a decision model returns a probability for each allowed
answer. We ask one `choice` question - text, reaction, or none - and, when
the answer is reaction, a second `choice` question for the emoji.

Any failure (disabled, timeout, bad response, unsupported endpoint) returns
None so the caller can fall through to the normal full-model path. The gate
is an optimization, never a new way to drop messages.

Relevant .env keys:
  CLEF_ENABLED          true/false. Unset = auto: enabled when
                        OPENAI_BASE_URL points at logfare.ai.
  CLEF_MODEL            clef (default) or clef-flash (faster/cheaper)
  CLEF_DECISIONS_URL    override the full decisions endpoint
  CLEF_TIMEOUT_SECONDS  request timeout, default 3
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

ACTIONS = ("text", "reaction", "none")

# Emoji choices for the reaction branch. Keys are what we send to Discord;
# values describe when each fits so Clef can pick.
DEFAULT_REACTION_EMOJIS: Dict[str, str] = {
    "👍": "acknowledgment, agreement, or approval",
    "👀": "noticed it / taking a look",
    "❤️": "appreciation or warmth",
    "😂": "something is funny",
    "🎉": "celebration or good news",
    "🤔": "thoughtful, considering it",
    "🙏": "thanks or please",
    "✅": "confirmed / done",
}


@dataclass
class ResponseDecision:
    """Outcome of one Clef gate call."""

    action: str  # text | reaction | none
    emoji: Optional[str] = None
    confidence: float = 0.0
    action_probabilities: Dict[str, float] = field(default_factory=dict)
    emoji_confidence: float = 0.0
    model: str = ""

    @property
    def should_respond(self) -> bool:
        return self.action != "none"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def clef_enabled() -> bool:
    """Auto-enable on Logfare; CLEF_ENABLED always wins when set."""
    default = "logfare" in (os.getenv("OPENAI_BASE_URL") or "").lower()
    return _env_bool("CLEF_ENABLED", default)


def _decisions_url() -> str:
    explicit = os.getenv("CLEF_DECISIONS_URL", "").strip()
    if explicit:
        return explicit
    base = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1"):
        return f"{base}/decisions"
    return f"{base}/v1/decisions"


def _answer_value(answers: Dict[str, Any], name: str) -> Dict[str, Any]:
    answer = answers.get(name)
    return answer if isinstance(answer, dict) else {}


def _parse_decision(payload: Dict[str, Any]) -> Optional[ResponseDecision]:
    """Parse Logfare's `{"result": {"answers": {...}}}` / bare answers shape."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        result = payload if isinstance(payload, dict) else {}
    answers = result.get("answers")
    if not isinstance(answers, dict):
        return None

    action_answer = _answer_value(answers, "action")
    action = action_answer.get("choice")
    if action not in ACTIONS:
        return None

    emoji_answer = _answer_value(answers, "emoji")
    emoji = emoji_answer.get("choice")

    return ResponseDecision(
        action=action,
        emoji=emoji if action == "reaction" else None,
        confidence=float(action_answer.get("confidence") or 0.0),
        action_probabilities={
            k: float(v) for k, v in (action_answer.get("probabilities") or {}).items()
        },
        emoji_confidence=float(emoji_answer.get("confidence") or 0.0),
        model=str(
            result.get("model")
            or (payload.get("model") if isinstance(payload, dict) else "")
            or ""
        ),
    )


def _build_questions(emojis: Dict[str, str]) -> Dict[str, Any]:
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "You are triaging a Discord conversation for a bot participant. "
                "Should the bot post a text message, add a lightweight emoji "
                "reaction, or stay silent? Prefer silence unless the bot has "
                "something genuinely useful or socially natural to add. A "
                "direct mention, a question aimed at the bot, or a request for "
                "help calls for text. A brief acknowledgment, agreement, "
                "appreciation, or joke with nothing substantive to add calls "
                "for a reaction. Low-value chatter, conversations between "
                "other people, and messages that do not need the bot call for "
                "silence."
            ),
            "criteria": {
                "text": (
                    "The bot should write a reply: it was directly addressed, "
                    "someone asked it something, it can help, or it has a "
                    "genuinely valuable contribution."
                ),
                "reaction": (
                    "A single emoji is the whole response: the bot wants to "
                    "acknowledge or agree without adding words."
                ),
                "none": (
                    "No response is appropriate: nothing useful to add, the "
                    "conversation does not involve the bot, or interrupting "
                    "would be noise."
                ),
            },
        },
        "emoji": {
            "type": "choice",
            "instructions": (
                "If the bot should react, which single emoji best fits the "
                "message? This answer is ignored when the action is not "
                "reaction."
            ),
            "criteria": emojis,
        },
    }


async def decide_response(
    state: str,
    *,
    emojis: Optional[Dict[str, str]] = None,
) -> Optional[ResponseDecision]:
    """Ask Clef what to do with a conversation state.

    Returns None when the gate is disabled or the call fails for any reason;
    callers must treat that as "run the normal model path".
    """
    if not clef_enabled():
        return None

    url = _decisions_url()
    if not url:
        return None

    api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("CLEF_MODEL", "clef").strip() or "clef"
    try:
        timeout = float(os.getenv("CLEF_TIMEOUT_SECONDS", "3"))
    except ValueError:
        timeout = 3.0

    body = {
        "model": model,
        "state": state,
        "questions": _build_questions(emojis or DEFAULT_REACTION_EMOJIS),
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as e:
        logger.warning(f"Clef decision gate failed, falling back to full model: {e}")
        return None

    decision = _parse_decision(payload)
    if decision is None:
        logger.warning("Clef decision gate returned an unusable response")
    return decision
