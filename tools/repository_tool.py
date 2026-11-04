"""
Repository tool definition (v0.6.1) - the bot's per-server file drive.

Write/management surface only: reading repository files goes through the
existing discord_tools get_attachment action (repo files are attachment rows).
"""


def get_repository_tool() -> dict:
    return {
        "name": "repository",
        "description": (
            "Your private file space for this server - a local folder that persists across "
            "restarts. People can drop files in for you, and you can keep whatever you decide "
            "is worth keeping, for whatever reason: something you wrote (save_file) or an "
            "attachment from the chat (save_attachment). Arrange or prune it however you like "
            "(rename, delete, nested folders). It's entirely yours and needs no upkeep - reach "
            "for it when something genuinely seems worth keeping or someone asks, and otherwise "
            "ignore it. To READ one of its files, use discord_tools get_attachment with the "
            "attachment_id shown in <repository>."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "save_file", "save_attachment", "delete", "rename"],
                    "description": "Repository action to execute",
                },
                "path": {
                    "type": "string",
                    "description": "[save_file/save_attachment/delete] Relative path inside the repository, e.g. 'notes/summary.md'. Optional for save_attachment (defaults to the source filename).",
                },
                "content": {
                    "type": "string",
                    "description": "[save_file] Full text content to write (UTF-8).",
                },
                "attachment_id": {
                    "type": "string",
                    "description": "[save_attachment] ID of an existing Discord attachment to copy into the repository",
                },
                "old_path": {
                    "type": "string",
                    "description": "[rename] Current relative path",
                },
                "new_path": {
                    "type": "string",
                    "description": "[rename] New relative path (must not exist)",
                },
                "scope": {
                    "type": "string",
                    "enum": ["server", "global"],
                    "description": "[list] server (default) lists this server's drive; global lists every server's, grouped by server.",
                },
            },
            "required": ["action"],
        },
    }
