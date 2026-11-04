"""
Unified Attachment Manager - local storage and image preparation.

Attachments are always saved to local disk. Images are additionally encoded
as base64 so they can be sent inline to the model as image content. Other
files stay on disk and are referenced by path / the Discord tools.
"""

import logging
from typing import Optional, Dict, TYPE_CHECKING
import discord

from core.local_storage_manager import LocalStorageManager
from core.attachment_classifier import AttachmentClassifier
from core.internal_constants import format_size
from core.attachment_database import AttachmentDatabase
from tools.image_processor import ImageProcessor

if TYPE_CHECKING:
    from core.config import BotConfig
    from core.message_memory import MessageMemory

logger = logging.getLogger(__name__)


class UnifiedAttachmentManager:
    """Orchestrates local attachment storage and image encoding."""

    def __init__(
        self,
        config: "BotConfig",
        message_memory: "MessageMemory"
    ):
        self.config = config
        self.local_storage = LocalStorageManager(
            config.attachments.local_storage.base_path
        )
        self.image_processor = ImageProcessor()
        self.attachment_db = AttachmentDatabase(message_memory._db)

    async def initialize(self) -> None:
        """Create schema and run migrations."""
        await self.attachment_db.create_schema()
        await self.attachment_db.migrate_messages_table()
        await self.attachment_db.migrate_repository_columns()
        logger.info("UnifiedAttachmentManager initialized with local storage")

    async def process_attachment(
        self,
        attachment: discord.Attachment,
        message: discord.Message,
        is_realtime: bool = True
    ) -> Optional[Dict]:
        """
        Save an attachment locally and prepare image data for the API.

        Returns a dict with attachment metadata, the local path, and a
        ``for_api`` entry for images (base64) or None otherwise.
        """
        att_type = AttachmentClassifier.classify(attachment.filename)
        logger.info(
            f"Processing {att_type} attachment: {attachment.filename} "
            f"({attachment.size} bytes)"
        )

        try:
            file_data = await attachment.read()
        except Exception as e:
            logger.error(f"Failed to download attachment {attachment.id}: {e}")
            return None

        try:
            return await self._process_attachment(
                attachment, message, file_data, att_type, is_realtime
            )
        except Exception as e:
            logger.error(f"Error processing attachment {attachment.id}: {e}", exc_info=True)
            return None

    async def _process_attachment(
        self,
        attachment: discord.Attachment,
        message: discord.Message,
        file_data: bytes,
        att_type: str,
        is_realtime: bool
    ) -> Optional[Dict]:
        local_path = await self.local_storage.save(
            file_data=file_data,
            server_id=str(message.guild.id) if message.guild else "DM",
            channel_id=str(message.channel.id),
            message_id=str(message.id),
            filename=attachment.filename
        )

        processed_base64 = None
        processed_mime = None

        if att_type == "image":
            image_result = await self._process_image(attachment, file_data, att_type)
            if image_result:
                processed_base64 = image_result["source"]["data"]
                processed_mime = image_result["source"]["media_type"]

        await self._store_attachment_record(
            attachment_id=str(attachment.id),
            message_id=str(message.id),
            server_id=str(message.guild.id) if message.guild else "DM",
            channel_id=str(message.channel.id),
            filename=attachment.filename,
            size_bytes=attachment.size,
            attachment_type=att_type,
            discord_url=attachment.url,
            local_path=local_path,
            processed_base64=processed_base64,
            processed_mime=processed_mime,
            content_type=AttachmentClassifier.guess_mime_type(attachment.filename)
        )

        for_api = None
        if att_type == "image" and processed_base64:
            for_api = {
                "method": "base64",
                "data": processed_base64,
                "media_type": processed_mime,
            }

        return {
            "attachment_id": str(attachment.id),
            "attachment_type": att_type,
            "filename": attachment.filename,
            "size_bytes": attachment.size,
            "local_path": local_path,
            "for_api": for_api,
        }

    async def delete_attachments_for_message(self, message_id: str) -> int:
        """Remove local copies and database rows for a deleted message."""
        async with self.attachment_db.db.execute(
            "SELECT attachment_id, local_path, filename FROM attachments WHERE message_id = ?",
            (str(message_id),)
        ) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return 0

        for attachment_id, local_path, filename in rows:
            if local_path and self.local_storage.exists(local_path):
                try:
                    await self.local_storage.delete(local_path)
                except Exception as e:
                    logger.warning(f"Could not delete local copy of {filename}: {e}")

        await self.attachment_db.db.execute(
            "DELETE FROM attachments WHERE message_id = ?", (str(message_id),)
        )
        await self.attachment_db.db.commit()

        logger.info(f"Purged {len(rows)} attachment(s) for deleted message {message_id}")
        return len(rows)

    @staticmethod
    def build_content_block(for_api: Optional[Dict], filename: str, role: str = "user") -> Optional[Dict]:
        """Content block for a processed attachment: images only, user turns."""
        if not for_api:
            return None
        if role != "user":
            return {"type": "text", "text": f"\n[Attachment: {filename}]"}
        if for_api.get("method") == "base64":
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": for_api["media_type"],
                    "data": for_api["data"],
                },
            }
        return None

    async def get_attachment_for_processing(self, attachment_id: str) -> Optional[Dict]:
        """
        Retrieve attachment data on demand.

        Images return ``{"method": "base64", ...}``; other files return
        ``{"method": "local", "data": <path>, ...}``. Returns None when the
        attachment is unknown or its local copy is gone.
        """
        async with self.attachment_db.db.execute(
            "SELECT * FROM attachments WHERE attachment_id = ?",
            (attachment_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            logger.warning(f"Attachment {attachment_id} not found in database")
            return None

        attachment_data = dict(row)
        local_path = attachment_data.get("local_path")
        processed_base64 = attachment_data.get("processed_base64")
        processed_mime = attachment_data.get("processed_mime")
        attachment_type = attachment_data.get("attachment_type")
        filename = attachment_data.get("filename")

        if attachment_type == "image":
            if processed_base64:
                return {
                    "method": "base64",
                    "data": processed_base64,
                    "media_type": processed_mime,
                }
            if local_path and self.local_storage.exists(local_path):
                try:
                    file_data = await self.local_storage.load(local_path)
                    image_result = await self.image_processor.process_bytes(filename, file_data)
                    if image_result:
                        b64 = image_result["source"]["data"]
                        mime = image_result["source"]["media_type"]
                        await self.attachment_db.db.execute(
                            "UPDATE attachments SET processed_base64 = ?, processed_mime = ? "
                            "WHERE attachment_id = ?",
                            (b64, mime, attachment_id)
                        )
                        await self.attachment_db.db.commit()
                        logger.info(f"Processed image on demand: {attachment_id}")
                        return {
                            "method": "base64",
                            "data": b64,
                            "media_type": mime,
                        }
                except Exception as e:
                    logger.error(f"On-demand image processing failed: {e}", exc_info=True)

        if local_path and self.local_storage.exists(local_path):
            return {"method": "local", "data": local_path, "filename": filename}

        logger.error(f"Cannot retrieve attachment {attachment_id}: local copy missing")
        return None

    async def _process_image(
        self,
        attachment: discord.Attachment,
        file_data: bytes,
        att_type: str
    ) -> Optional[Dict]:
        if att_type != "image":
            return None
        try:
            result = await self.image_processor.process_attachment(attachment)
            if result:
                logger.info(
                    f"Compressed image {attachment.filename}: "
                    f"{attachment.size} bytes -> base64 encoded"
                )
            return result
        except Exception as e:
            logger.error(f"Image processing failed for {attachment.filename}: {e}", exc_info=True)
            return None

    async def _store_attachment_record(
        self,
        attachment_id: str,
        message_id: str,
        server_id: str,
        channel_id: str,
        filename: str,
        size_bytes: int,
        attachment_type: str,
        **kwargs
    ) -> None:
        discord_url = kwargs.get("discord_url")
        local_path = kwargs.get("local_path")
        processed_base64 = kwargs.get("processed_base64")
        processed_mime = kwargs.get("processed_mime")
        content_type = kwargs.get("content_type")

        try:
            await self.attachment_db.db.execute(
                """
                INSERT OR IGNORE INTO attachments (
                    attachment_id, message_id, server_id, channel_id,
                    filename, size_bytes, content_type, attachment_type,
                    discord_url, local_path,
                    processed_base64, processed_mime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id, message_id, server_id, channel_id,
                    filename, size_bytes, content_type, attachment_type,
                    discord_url, local_path,
                    processed_base64, processed_mime
                )
            )
            await self.attachment_db.db.commit()

            logger.info(
                f"Stored attachment record: {filename} "
                f"(type={attachment_type}, size={format_size(size_bytes)})"
            )

        except Exception as e:
            logger.error(f"Failed to store attachment record {attachment_id}: {e}", exc_info=True)
            raise
