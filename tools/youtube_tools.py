"""
YouTube and Video Tools - Extract transcripts and metadata from YouTube URLs.
"""

import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Try to import youtube-transcript-api if available
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _YOUTUBE_AVAILABLE = True
except ImportError:
    _YOUTUBE_AVAILABLE = False


def extract_youtube_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


WATCH_YOUTUBE_TOOL = {
    "name": "watch_youtube",
    "description": (
        "Extract the transcript and text content from a YouTube video URL "
        "so you can read, summarize, or answer questions about it. "
        "Provide a valid YouTube video URL or video ID."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The YouTube video URL or ID to watch/read.",
            }
        },
        "required": ["url"],
    },
}


def get_watch_youtube_tool() -> dict:
    return WATCH_YOUTUBE_TOOL


async def execute_watch_youtube(tool_input: dict) -> str:
    """Fetch transcript for a YouTube video."""
    url_or_id = tool_input.get("url", "")
    video_id = extract_youtube_id(url_or_id) or url_or_id.strip()

    if not video_id or len(video_id) != 11:
        return f"Error: Invalid YouTube URL or video ID: {url_or_id}"

    if not _YOUTUBE_AVAILABLE:
        return "Error: youtube-transcript-api is not installed in this environment."

    try:
        # Fetch transcript synchronously via to_thread
        import asyncio
        transcript_list = await asyncio.to_thread(
            YouTubeTranscriptApi.get_transcript, video_id
        )
        
        full_text = " ".join([chunk.get("text", "") for chunk in transcript_list])
        # Truncate if too massive
        if len(full_text) > 25000:
            full_text = full_text[:25000] + "\n...(transcript truncated due to length)"

        return f"YouTube Transcript for video {video_id}:\n\n{full_text}"
    except Exception as e:
        logger.error(f"Failed to fetch YouTube transcript for {video_id}: {e}")
        return f"Error fetching YouTube transcript: {e}"
