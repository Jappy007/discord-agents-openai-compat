"""
Reaction tools - add/remove reactions to Discord messages.

Reactions are lightweight signals (acknowledgment, agreement, etc.)
without posting a full message. Use when a reply would be too heavy.
"""

REACT_TOOL = {
    "name": "add_reaction",
    "description": (
        "React to a message with an emoji. Use for acknowledgments, "
        "agreement, or lightweight signals instead of a full reply - "
        "sometimes a reaction is more appropriate than a message. "
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


def get_reaction_tools() -> list:
    return [REACT_TOOL, REMOVE_REACTION_TOOL]


def get_add_reaction_tool() -> dict:
    return REACT_TOOL


def get_remove_reaction_tool() -> dict:
    return REMOVE_REACTION_TOOL


async def execute_reaction_tool(tool_name: str, tool_input: dict, message) -> str:
    """
    Execute an add_reaction or remove_reaction tool call.

    Resolves the target message (channel history lookup falls back to
    the triggering message's channel) and applies/removes the emoji.
    """
    import discord

    message_id = (tool_input.get("message_id") or "").strip()
    emoji = (tool_input.get("emoji") or "").strip()
    if not message_id or not emoji:
        return "Error: message_id and emoji are required."

    try:
        target_id = int(message_id)
    except ValueError:
        return f"Error: '{message_id}' is not a valid message id."

    # Same channel as the triggering message; reactions are channel-scoped
    channel = message.channel
    try:
        target = await channel.fetch_message(target_id)
    except discord.NotFound:
        return f"Error: message {message_id} not found in this channel."
    except discord.HTTPException as e:
        return f"Error: could not fetch message {message_id}: {e}"

    try:
        if tool_name == "add_reaction":
            await target.add_reaction(emoji)
            return f"Reacted with {emoji} to message {message_id}."
        else:
            await target.remove_reaction(emoji, message.guild.me if message.guild else None)
            return f"Removed reaction {emoji} from message {message_id}."
    except discord.NotFound:
        return f"Error: emoji {emoji} not found."
    except discord.Forbidden:
        return "Error: missing permission to react on that message."
    except discord.HTTPException as e:
        return f"Error: reaction failed: {e}"