"""Helpers for reading text and image data from MoFox messages."""

from __future__ import annotations

from typing import Any


def text_from_message(message: Any) -> str:
    """Return the readable text from a text or media message."""

    text = str(getattr(message, "processed_plain_text", "") or "").strip()
    if text:
        return text
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return str(content.get("text", "") or "").strip()
    return ""


def media_from_message(message: Any) -> list[dict[str, Any]]:
    """Return media items from a message."""

    extra = getattr(message, "extra", {}) or {}
    if isinstance(extra, dict) and isinstance(extra.get("media"), list):
        return [item for item in extra["media"] if isinstance(item, dict)]
    content = getattr(message, "content", {})
    if isinstance(content, dict) and isinstance(content.get("media"), list):
        return [item for item in content["media"] if isinstance(item, dict)]
    return []


def first_image_data(message: Any) -> str:
    """Return the first image as raw base64 or data URI."""

    for item in media_from_message(message):
        if str(item.get("type", "")).lower() != "image":
            continue
        data = str(item.get("data", "") or "").strip()
        if data.startswith("base64://"):
            return data.removeprefix("base64://").strip()
        if data.startswith("base64|"):
            return data.split("|", 1)[1].strip()
        return data
    return ""
