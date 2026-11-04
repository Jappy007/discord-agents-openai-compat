"""
Attachment type classifier for Discord attachments.
Categorizes files by extension and provides utility methods for file type handling.
"""

import mimetypes
from pathlib import Path
from typing import List, Set, Dict


class AttachmentClassifier:
    """Static utility class for classifying file attachments by type"""

    # Extension to category mappings
    EXTENSION_CATEGORIES: Dict[str, Set[str]] = {
        'image': {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'},
        'video': {'.mp4', '.mov', '.avi', '.webm', '.mkv'},
        'audio': {'.mp3', '.wav', '.ogg', '.flac'},
        'document': {'.pdf', '.docx', '.doc', '.txt', '.md', '.rtf', '.odt'},
        'spreadsheet': {'.xlsx', '.xls', '.csv', '.ods'},
        'code': {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.rs', '.go', '.rb',
                 '.json', '.yaml', '.yml', '.xml', '.html', '.css', '.php', '.sh'},
        'archive': {'.zip', '.tar', '.gz', '.rar', '.7z'},
    }

    @staticmethod
    def get_extension(filename: str) -> str:
        """
        Extract lowercase extension from filename without dot.

        Args:
            filename: Name of the file

        Returns:
            Extension without dot (e.g., "csv" from "data.CSV")
        """
        path = Path(filename)
        ext = path.suffix.lower()
        return ext[1:] if ext else ''

    @staticmethod
    def classify(filename: str) -> str:
        """
        Classify file into category based on extension.

        Args:
            filename: Name of the file

        Returns:
            Category string ('image', 'document', 'spreadsheet', 'code', 'archive', 'other')
        """
        path = Path(filename)

        # Handle double extensions like .tar.gz
        suffixes = [s.lower() for s in path.suffixes]

        # Check each suffix against categories
        for suffix in reversed(suffixes):
            for category, extensions in AttachmentClassifier.EXTENSION_CATEGORIES.items():
                if suffix in extensions:
                    return category

        return 'other'

    IMAGE_MEDIA_TYPES = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'gif': 'image/gif', 'webp': 'image/webp',
    }

    @staticmethod
    def image_media_type(filename: str) -> str:
        """Media type for image blocks (image/jpeg fallback - Discord's most common)."""
        ext = AttachmentClassifier.get_extension(filename).lower()
        return AttachmentClassifier.IMAGE_MEDIA_TYPES.get(ext, 'image/jpeg')

    @staticmethod
    def guess_mime_type(filename: str) -> str:
        """
        Guess MIME type based on file extension.

        Args:
            filename: Name of the file

        Returns:
            MIME type string (e.g., "text/csv")
        """
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or 'application/octet-stream'


