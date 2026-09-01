"""
reaction_tools - add/remove reactions to Discord messages.

Reactions are lightweight signals (acknowledgment, agreement, etc.)
without posting a full message. Use when a reply would be too heavy.
"""

REACT_TOOL = {
    "name": "add_reaction",
    "description": (
        "React to a message with an emoji. Use for acknowledgments, "
        "agreement, or lightweight signals instead of a full reply. "
        "Each call adds one reaction to one message. You can add "
        "multiple reactions to the same message with separate calls. "
        "Use standard Unicode emoji (e.g. 👍 👎 😂 ❤️ 🎉 👀 ✅ ❌) or "
        "custom Discord emoji by ID (e.g. <:emoji_name:123456789>). "
        "Reactions are instant and don't count against rate limits."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "The Discord message ID to react to (from <recent_messages> context).",
            },
            "emoji": {
                "type": "string",
                "description": "The emoji to react with. Standard Unicode emoji or custom emoji string like <:name:123456789>.",
            },
        },
        "required": ["message_id", "emoji"],
    },
}

REMOVE_REACTION_TOOL = {
    "name": "remove_reaction",
    "description": (
        "Remove a reaction you previously added to a message. "
        "Use if you added the wrong reaction or want to retract it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "The Discord message ID to remove the reaction from.",
            },
            "emoji": {
                "type": "string",
                "description": "The exact emoji string you want to remove.",
            },
        },
        "required": ["message_id", "emoji"],
    },
}


def get_reaction_tool() -> dict:
    return REACT_TOOL


def get_remove_reaction_tool() -> dict:
    return REMOVE_REACTION_TOOL