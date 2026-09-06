"""
Minecraft Client Integration

Replaces DiscordClient when the bot runs in Minecraft mode.
Spawns the Node/Mineflayer bridge, translates in-game events into
Discord-like shim messages, and feeds them into the existing reactive
engine pipeline.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .minecraft_shim import MCChannel, MCGuild, MCUser, build_shim_message

logger = logging.getLogger(__name__)


class MinecraftClient:
    """
    Client that connects to a Minecraft server via the Mineflayer bridge
    and presents the same interface to the reactive engine as DiscordClient.
    """

    def __init__(
        self,
        config,
        reactive_engine,
        agentic_engine,
        message_memory,
        user_cache,
        conversation_logger,
        memory_manager,
    ):
        self.config = config
        self.reactive_engine = reactive_engine
        self.agentic_engine = agentic_engine
        self.message_memory = message_memory
        self.user_cache = user_cache
        self.conversation_logger = conversation_logger
        self.memory_manager = memory_manager

        self.bot_name = config.minecraft.bot_name
        self.user = MCUser(
            uuid="0",
            name=self.bot_name,
            display_name=self.bot_name,
            bot=True,
        )
        self.guild = MCGuild(
            guild_id="minecraft",
            name=config.minecraft.server_name or "Minecraft Server",
            me=self.user,
        )
        self.public_channel = MCChannel(
            channel_id="minecraft:chat",
            name="minecraft-chat",
            send_callback=self._send_chat,
            guild=self.guild,
        )
        self.dm_channels = {}  # player_uuid -> MCChannel

        self._process: Optional[subprocess.Process] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._read_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._last_activity = datetime.now(timezone.utc)
        self._idle_threshold_seconds = config.minecraft.idle_threshold_seconds
        self._status = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Spawn the Mineflayer bridge and start reading events."""
        bridge_dir = Path(__file__).parent.parent / "mc_bridge"
        bridge_js = bridge_dir / "bridge.js"
        if not bridge_js.exists():
            raise FileNotFoundError(f"Mineflayer bridge not found: {bridge_js}")

        cfg = self.config.minecraft
        env = os.environ.copy()
        env.setdefault("MC_HOST", cfg.host)
        env.setdefault("MC_PORT", str(cfg.port))
        env.setdefault("MC_USERNAME", cfg.username)
        env.setdefault("MC_AUTH", cfg.auth)
        env.setdefault("MC_VERSION", cfg.version)
        env.setdefault("MC_BOT_NAME", cfg.bot_name)
        env.setdefault("MC_MCP_PORT", str(cfg.mcp_port))
        if cfg.spawn:
            env.setdefault("MC_SPAWN_X", str(cfg.spawn.x))
            env.setdefault("MC_SPAWN_Y", str(cfg.spawn.y))
            env.setdefault("MC_SPAWN_Z", str(cfg.spawn.z))
        env.setdefault("MC_SPAWN_RADIUS", str(cfg.spawn_radius))

        bridge_config = {
            "host": cfg.host,
            "port": cfg.port,
            "username": cfg.username,
            "auth": cfg.auth,
            "version": cfg.version,
            "bot_name": cfg.bot_name,
            "spawn": cfg.spawn,
            "spawn_radius": cfg.spawn_radius,
        }

        logger.info(f"Starting Mineflayer bridge for {cfg.username} on {cfg.host}:{cfg.port}")
        node_path = "/usr/bin/node"
        if not os.path.exists(node_path):
            node_path = "node"
        self._process = await asyncio.create_subprocess_exec(
            node_path,
            str(bridge_js),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(bridge_dir),
            env=env,
        )

        self._reader = self._process.stdout
        self._writer = self._process.stdin

        # Send bridge config as first line.
        self._write_stdin(json.dumps(bridge_config))

        self._read_task = asyncio.create_task(self._read_loop())
        self._idle_task = asyncio.create_task(self._idle_loop())

        # Seed reactive engine list_servers / resolver with fake guild.
        self.reactive_engine.list_servers = lambda: [self.guild.name]
        self.reactive_engine.repository_manager.guild_name_resolver = (
            lambda gid: self.guild.name if gid == "minecraft" else None
        )

    async def close(self):
        """Graceful shutdown."""
        if self._read_task:
            self._read_task.cancel()
        if self._idle_task:
            self._idle_task.cancel()
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def _write_stdin(self, line: str):
        if self._writer:
            self._writer.write((line + "\n").encode())

    async def _send_chat(self, text: str):
        """Callback used by MCChannel.send()."""
        self._write_stdin(json.dumps({"type": "chat", "text": text}))

    async def _send_whisper(self, player: str, text: str):
        self._write_stdin(json.dumps({"type": "whisper", "player": player, "text": text}))

    # ------------------------------------------------------------------
    # Event reading
    # ------------------------------------------------------------------

    async def _read_loop(self):
        while True:
            try:
                line = await self._reader.readline()
            except Exception as e:
                logger.error(f"Bridge read error: {e}")
                await asyncio.sleep(1)
                continue
            if not line:
                await asyncio.sleep(0.1)
                continue
            try:
                event = json.loads(line.decode().strip())
            except json.JSONDecodeError:
                continue
            await self._handle_bridge_event(event)

    async def _handle_bridge_event(self, event):
        etype = event.get("type")

        if etype == "log":
            level = event.get("level", "info")
            getattr(logger, level, logger.info)(f"[bridge] {event.get('message')}")
            return

        if etype == "status":
            self._status = event.get("data", {})
            return

        if etype == "login":
            logger.info(f"Mineflayer logged in as {event.get('username')}")
            return

        if etype == "spawn":
            logger.info(f"Mineflayer spawned at {event.get('position')}")
            return

        if etype in ("kicked", "end"):
            logger.warning(f"Mineflayer connection event: {etype}")
            return

        if etype == "chat":
            await self._on_player_chat(
                player=event["player"],
                uuid=event.get("uuid") or event["player"],
                text=event["message"],
                whisper=event.get("whisper", False),
            )
            return

        if etype == "join":
            await self._on_system_event(
                f"[Player {event['player']} joined the server]",
                event.get("uuid") or event["player"],
                event["player"],
            )
            return

        if etype == "leave":
            await self._on_system_event(
                f"[Player {event['player']} left the server]",
                event.get("uuid") or event["player"],
                event["player"],
            )
            return

        if etype in ("death", "death_message"):
            text = event.get("text") or "[Bot died]"
            await self._on_system_event(text, "0", "server")
            return

        if etype == "advancement":
            await self._on_system_event(
                f"[{event['player']} made the advancement {event['advancement']}]",
                event.get("uuid") or event["player"],
                event["player"],
            )
            return

        if etype == "aggression":
            # Logged as a system note so the bot can reference it.
            weapon = "weapon" if event.get("weapon") else "fist"
            await self._on_system_event(
                f"[{event['player']} hit the bot with a {weapon}]",
                event.get("uuid") or event["player"],
                event["player"],
            )
            return

    # ------------------------------------------------------------------
    # Message pipeline (mirrors DiscordClient.on_message)
    # ------------------------------------------------------------------

    def _environment_prefix(self) -> str:
        s = self._status
        if not s:
            return ""
        pos = s.get("position", {})
        nearby = s.get("nearby", [])
        nearby_str = ", ".join(f"{p['name']}({p['distance']}m)" for p in nearby[:5])
        return (
            f"[ENV: pos=({pos.get('x')},{pos.get('y')},{pos.get('z')}) "
            f"hp={s.get('health')}/{20} food={s.get('food')} "
            f"held={s.get('held')} time={s.get('timeOfDay')} "
            f"nearby={nearby_str or 'none'}]\n"
        )

    async def _on_player_chat(self, player: str, uuid: str, text: str, whisper: bool):
        self._last_activity = datetime.now(timezone.utc)

        if whisper:
            channel = self._get_dm_channel(player, uuid)
        else:
            channel = self.public_channel

        env_prefix = self._environment_prefix() if not whisper else ""
        full_content = env_prefix + text

        message = build_shim_message(
            text=full_content,
            player_name=player,
            player_uuid=uuid,
            channel=channel,
            bot_name=self.bot_name,
            guild=self.guild,
            is_whisper=whisper,
        )
        await self._process_message(message)

    async def _on_system_event(self, text: str, uuid: str, player_name: str):
        message = build_shim_message(
            text=text,
            player_name=player_name,
            player_uuid=uuid,
            channel=self.public_channel,
            bot_name=self.bot_name,
            guild=self.guild,
            event_type="system",
        )
        await self._process_message(message, store_only=True)

    async def _process_message(self, message, store_only: bool = False):
        # Store all messages (including bot's own if we ever emit them).
        try:
            await self.message_memory.add_message(message)
        except Exception as e:
            logger.error(f"Error storing message: {e}")

        # Update user cache with shim-compatible data.
        try:
            await self.user_cache.update_user(message.author, increment_messages=True)
        except Exception as e:
            logger.error(f"Error updating user cache: {e}")

        if store_only:
            return

        # Don't process bot's own messages.
        if message.author == self.user:
            return

        # Urgent = name mention or whisper.
        is_urgent = message.whisper or (self.bot_name.lower() in message.content.lower())

        if is_urgent:
            logger.info(f"Urgent message from {message.author.display_name}: {message.content[:60]}...")
            try:
                await self.reactive_engine.handle_urgent(message)
            except Exception as e:
                logger.error(f"Error handling urgent message: {e}", exc_info=True)
                try:
                    await message.channel.send("something went sideways handling that - try again in a moment?")
                except Exception:
                    pass
        else:
            channel_id = str(message.channel.id)
            message_id = message.id
            self.reactive_engine.add_pending_message(channel_id, message_id)
            logger.debug(
                f"Message {message_id} from {message.author.name} in "
                f"#{message.channel.name} (stored, added to pending)"
            )

    def _get_dm_channel(self, player_name: str, uuid: str) -> MCChannel:
        if uuid not in self.dm_channels:
            recipient = MCUser(uuid, player_name)
            self.dm_channels[uuid] = MCChannel(
                channel_id=f"minecraft:dm:{uuid}",
                name=f"DM · {player_name}",
                send_callback=lambda text, p=player_name: self._send_whisper(p, text),
                guild=None,
                recipient=recipient,
            )
        return self.dm_channels[uuid]

    # ------------------------------------------------------------------
    # Idle / autonomous director
    # ------------------------------------------------------------------

    async def _idle_loop(self):
        while True:
            await asyncio.sleep(60)
            idle_seconds = (datetime.now(timezone.utc) - self._last_activity).total_seconds()
            if idle_seconds >= self._idle_threshold_seconds:
                await self._idle_tick()

    async def _idle_tick(self):
        """Trigger an autonomous decision when nobody has interacted."""
        logger.debug("Idle threshold reached; running autonomous tick")
        # Build a synthetic message from the bot to itself, which the reactive
        # engine can treat as a non-urgent prompt. In practice we call the
        # agentic engine directly if available, otherwise skip.
        if not self.agentic_engine:
            return
        try:
            # TODO: wire to agentic_engine.idle_tick once implemented.
            # For now, log the event so memory knows the bot is alive.
            await self._on_system_event(
                "[Bot is idle and considering what to do next]",
                "0",
                "server",
            )
        except Exception as e:
            logger.error(f"Idle tick error: {e}")

    # ------------------------------------------------------------------
    # DiscordClient-compatible attributes used by engines
    # ------------------------------------------------------------------

    @property
    def guilds(self):
        return [self.guild]

    def get_guild(self, guild_id):
        if str(guild_id) == "minecraft":
            return self.guild
        return None
