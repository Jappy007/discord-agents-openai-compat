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
        # Convert UUID to numeric ID using base 16 (hexadecimal)
        try:
            self.id = int(uuid.replace("-", "")[:18], 16) or 1
        except ValueError:
            # Fallback if conversion fails
            self.id = hash(uuid) & 0xFFFFFFFFFFFFFFFF
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

    @property
    def mention(self):
        """Discord-compatible mention string."""
        return f"<@{self.id}>"


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
        # In-memory ring of recent messages so fetch_message/history work
        # without a Minecraft history API (message_id -> MCMessage, oldest first)
        self._messages = {}
        self._max_ring = 2000

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

    def remember(self, message: "MCMessage"):
        """Register a message in the ring (called by MinecraftClient)."""
        self._messages[message.id] = message
        if len(self._messages) > self._max_ring:
            for old_id in list(self._messages.keys())[:len(self._messages) - self._max_ring]:
                del self._messages[old_id]

    def typing(self):
        """No-op context manager (Minecraft has no typing indicator)."""
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def _cm():
            yield
        return _cm()

    async def fetch_message(self, message_id: int):
        """Look up a message in the ring (no Minecraft message-history API)."""
        msg = self._messages.get(int(message_id))
        if msg is None:
            raise LookupError(f"fetch_message: message {message_id} not in {self.name}")
        return msg

    async def history(self, *args, **kwargs):
        """Yield ring messages like discord.py history - newest first by default."""
        limit = kwargs.get("limit")
        after = kwargs.get("after")
        before = kwargs.get("before")
        oldest_first = kwargs.get("oldest_first", False)
        msgs = list(self._messages.values())
        if after is not None:
            if isinstance(after, datetime):
                msgs = [m for m in msgs if m.created_at > after]
            else:
                msgs = [m for m in msgs if m.id > int(after)]
        if before is not None:
            if isinstance(before, datetime):
                msgs = [m for m in msgs if m.created_at < before]
            else:
                msgs = [m for m in msgs if m.id < int(before)]
        ordered = msgs if oldest_first else list(reversed(msgs))
        for m in ordered[:limit] if limit else ordered:
            yield m


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
    reactions: List[Any] = field(default_factory=list)  # Minecraft has no reactions

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
