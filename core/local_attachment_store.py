"""
Local Attachment Store - disk-backed delivery channel for generated files.

The Files API / code-execution container are Anthropic-only server features;
under LLM_PROVIDER=openai_compatible they are stubbed out (FeatureNotSupportedError).
This store gives client-side tools a place to write generated deliverables
(pptx, ...) so they can ride send_message's attach_outputs / end-of-turn file
delivery exactly like container outputs do.

Layout: persistence/outputs/{bot_id}/ - created lazily. Files survive across
turns (the bot is long-lived) and are name-addressed (sanitized), which is all
the send_message tool needs; the store deliberately has no DB or expiry so a
file can be attached even a turn or two after it was created.
"""
import os
import logging
import shutil
from pathlib import Path
from typing import Optional

import aiofiles

logger = logging.getLogger(__name__)


class LocalAttachmentStore:
    """Minimal persistent output directory with safe, validated file access."""

    def __init__(self, base_path: str = "persistence/outputs", bot_id: str = "bot"):
        self.root = Path(base_path) / bot_id
        self.root.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalAttachmentStore initialized at {self.root}")

    def _resolve(self, filename: str) -> Path:
        """Resolve a (possibly user-supplied) filename inside the store root.

        Rejects anything that could escape the jail - absolute paths and ..
        segments. The filenames here are model-supplied strings, so the jail
        is a genuine security boundary, not just hygiene.
        """
        name = Path(filename or "").name
        if not name or name in (".", ".."):
            raise ValueError(f"Invalid local output filename: {filename!r}")
        resolved = (self.root / name).resolve()
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError:
            raise ValueError(f"Filename escapes local output store: {filename!r}")
        return resolved

    def path_for(self, filename: str) -> Path:
        """Absolute path a file WOULD live at, sanitized to the store root."""
        return self._resolve(filename)

    async def save(self, filename: str, data: bytes) -> str:
        """Write bytes to the store. Returns the absolute on-disk path."""
        path = self._resolve(filename)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        logger.info(f"Local output saved: {filename} ({len(data)} bytes) -> {path}")
        return str(path)

    async def load(self, filename: str) -> Optional[bytes]:
        """Read a file from the store. None if it doesn't exist or is unreadable."""
        path = self._resolve(filename)
        if not path.is_file():
            return None
        try:
            async with aiofiles.open(path, "rb") as f:
                return await f.read()
        except Exception as e:
            logger.error(f"Failed to read local output {filename}: {e}")
            return None

    def exists(self, filename: str) -> bool:
        try:
            return self._resolve(filename).is_file()
        except ValueError:
            return False

    def list_files(self) -> list:
        """Names of files currently in the store, newest last. For tool results."""
        if not self.root.is_dir():
            return []
        return sorted(
            (p.name for p in self.root.iterdir() if p.is_file()),
            key=lambda n: (self.root / n).stat().st_mtime,
            reverse=True,
        )

    async def delete(self, filename: str) -> bool:
        """Remove a file from the store (not currently exposed as a tool)."""
        try:
            path = self._resolve(filename)
        except ValueError:
            return False
        if not path.is_file():
            return False
        try:
            os.remove(path)
            logger.info(f"Local output deleted: {filename}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete local output {filename}: {e}")
            return False


def sanitize_filename(name: str) -> str:
    """Sanitize a model/context-supplied filename to a safe basename."""
    return Path(name or "").name or "output.bin"


def build_readable_output_paths(names: list) -> str:
    """Render the store's files for tool_result text (empty -> '')."""
    if not names:
        return ""
    return "Files currently saved: " + ", ".join(names)