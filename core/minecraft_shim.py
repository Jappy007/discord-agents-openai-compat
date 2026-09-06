"""
Minecraft shim objects.

These mimic the discord.py interface just enough for the existing
MessageMemory, UserCache, ReactiveEngine, and ContextBuilder to work
unchanged when the bot is connected to Minecraft instead of Discord.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Any

logger = logging.getLogger(__name__)


class MCUser:
    """Fake Discord user/member backed by a Minecraft player."""

    def __init__(self, uuid: str, name: str, display_name: str = None, bot: bool = False):
        self.id = int(uuid.replace("-", "")[:18]) or 1  # numeric-ish id
        self.uuid = uuid
        self.name = name
        self.display_name = display_name or name
        self.bot = bot
        self.system = False
        self.discriminator = "0000"
        self.global_name = display_name or name

    def __str__(self):
        return self.display_name

    def __eq__(self, other):
        if isinstance(other, MCUser):
            return self.uuid == other.uuid
        return False

    def __hash__(self):
        return hash(self.uuid)


class MCGuild:
    """Fake Discord guild representing the Minecraft server."""

    def __init__(self, guild_id: str, name: str, me: MCUser):
        try:
            self.id = int(guild_id)
        except ValueError:
            self.id = int(hash(guild_id) % 10**10)
        self.name = name
        self.me = me
        self.member_count = 0
        self._members = {}
        self.text_channels = []
        self.voice_channels = []
        self.text_channels = []
        self.voice_channels = []
        self.threads = []

    def get_member(self, user_id):
        return self._members.get(str(user_id))

    async def fetch_member(self, user_id):
        return self._members.get(str(user_id))

    def add_member(self, user: MCUser):
        self._members[str(user.id)] = user


class MCChannel:
    """Fake Discord channel for Minecraft public chat or a DM channel."""

    def __init__(self, channel_id: str, name: str, send_callback, guild: Optional[MCGuild] = None,
                 recipient: Optional[MCUser] = None):
        try:
            self.id = int(channel_id)
        except ValueError:
            self.id = int(hash(channel_id) % 10**10)
        self.channel_id = channel_id
        self.name = name
        self._send = send_callback
        self.guild = guild
        self.recipient = recipient

    async def send(self, content: str, **kwargs):
        """Send chat to the bridge. Re-chunks to Minecraft's 256 char limit."""
        if not content:
            return
        # Minecraft max chat length is 256; split intelligently.
        chunks = []
        remaining = content
        while remaining:
            if len(remaining) <= 256:
                chunks.append(remaining)
                break
            cut = remaining.rfind(' ', 0, 257)
            if cut <= 0:
                cut = 256
            chunks.append(remaining[:cut])
            remaining = remaining[cut:].lstrip()

        for chunk in chunks:
            await self._send(chunk)
            await asyncio.sleep(0.4)

    async def typing(self):
        """No-op context manager (Minecraft has no typing indicator)."""
        class _CM:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        return _CM()


@dataclass
class MCMessage:
    """Fake Discord message for a Minecraft chat/whisper/system event."""

    id: int
    content: str
    author: MCUser
    channel: MCChannel
    created_at: datetime
    guild: Optional[MCGuild]
    mentions: List[MCUser] = field(default_factory=list)
    attachments: List[Any] = field(default_factory=list)
    embeds: List[Any] = field(default_factory=list)
    reference: Optional[Any] = None
    whisper: bool = False
    event_type: Optional[str] = None

    @property
    def jump_url(self):
        return ""


def build_shim_message(
    text: str,
    player_name: str,
    player_uuid: str,
    channel: MCChannel,
    bot_name: str,
    guild: Optional[MCGuild] = None,
    is_whisper: bool = False,
    event_type: Optional[str] = None,
    message_id: Optional[int] = None,
) -> MCMessage:
    """Build a shim message, detecting name-mentions."""
    author = MCUser(player_uuid, player_name)
    if guild:
        guild.add_member(author)

    mentions = []
    if bot_name and bot_name.lower() in text.lower():
        mentions.append(guild.me if guild else MCUser("0", bot_name, bot_name, bot=True))

    return MCMessage(
        id=message_id or int(datetime.now(timezone.utc).timestamp() * 1000),
        content=text,
        author=author,
        channel=channel,
        created_at=datetime.now(timezone.utc),
        guild=guild,
        mentions=mentions,
        whisper=is_whisper,
        event_type=event_type,
    )
