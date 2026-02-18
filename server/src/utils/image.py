"""Image processing utilities for screenshot optimization.

Downscales and base64-encodes JPEG screenshots captured by
Playwright.  Used by the browser session (client display) and
the agent base class (LLM vision payloads).

Playwright captures screenshots as JPEG at quality 72 (the
client-display quality).  Client display only needs downscaling
when the image exceeds ``_MAX_WIDTH``.  LLM vision recompresses
at a lower quality and smaller size to minimize upload time and
token usage.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

# ── Client display settings ─────────────────────────────────
# Maximum width before downscaling.  iPad screenshots are
# 2048 px wide due to ``device_scale_factor=2``; the extra
# resolution wastes bandwidth (client) and token budget (LLM).
_MAX_WIDTH = 1280


# ── LLM vision settings ─────────────────────────────────────
# Smaller / more compressed images for LLM vision analysis.
# OpenAI's vision models resize to fit within 2048×2048 and
# then tile at 512 px.  768 px wide is enough for detecting
# buttons, text, and overlays while keeping the payload
# small and reducing upload / tokenization time.
_LLM_MAX_WIDTH = 768
_LLM_JPEG_QUALITY = 50


def downscale_jpeg(
    jpeg_bytes: bytes,
    *,
    max_width: int = _MAX_WIDTH,
    quality: int | None = None,
) -> tuple[bytes, int, int]:
    """Downscale a JPEG screenshot and optionally re-compress.

    When *quality* is ``None`` the image is only touched if it
    exceeds *max_width* — it is returned as-is when already
    small enough, avoiding a redundant decode/encode cycle.

    Args:
        jpeg_bytes: Raw JPEG image bytes.
        max_width: Downscale images wider than this.
        quality: When set, re-encode at this JPEG quality
            (1-95) regardless of whether the image was
            downscaled.

    Returns:
        Tuple of (jpeg_bytes, final_width, final_height).
    """
    img: Image.Image = Image.open(io.BytesIO(jpeg_bytes))
    try:
        needs_resize = img.width > max_width
        needs_reencode = quality is not None

        if not needs_resize and not needs_reencode:
            return jpeg_bytes, img.width, img.height

        if needs_resize:
            ratio = max_width / img.width
            resized = img.resize(
                (max_width, int(img.height * ratio)),
                Image.Resampling.LANCZOS,
            )
            img.close()
            img = resized

        if img.mode in ("RGBA", "P"):
            converted = img.convert("RGB")
            img.close()
            img = converted

        buf = io.BytesIO()
        img.save(
            buf,
            format="JPEG",
            quality=quality or 72,
            optimize=True,
        )
        return buf.getvalue(), img.width, img.height
    finally:
        img.close()


def screenshot_to_data_url(jpeg_bytes: bytes) -> str:
    """Convert raw JPEG bytes to an optimised data-URL string.

    Downscales if the image exceeds ``_MAX_WIDTH``; otherwise
    base64-encodes the bytes directly without re-encoding.
    Used for **client display**.

    Args:
        jpeg_bytes: Raw JPEG screenshot bytes.

    Returns:
        A ``data:image/jpeg;base64,...`` string.
    """
    out_bytes, _, _ = downscale_jpeg(jpeg_bytes)
    b64 = base64.b64encode(out_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def optimize_for_llm(
    screenshot_bytes: bytes,
) -> tuple[str, int]:
    """Aggressively optimize a screenshot for LLM vision.

    Downscales to ``_LLM_MAX_WIDTH`` and re-compresses at
    ``_LLM_JPEG_QUALITY`` to minimise upload size and improve
    LLM response latency.

    Args:
        screenshot_bytes: Raw JPEG screenshot bytes.

    Returns:
        Tuple of (``data:image/jpeg;base64,...`` string,
        compressed byte count).
    """
    jpeg_bytes, _, _ = downscale_jpeg(
        screenshot_bytes,
        max_width=_LLM_MAX_WIDTH,
        quality=_LLM_JPEG_QUALITY,
    )
    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
    return (
        f"data:image/jpeg;base64,{b64}",
        len(jpeg_bytes),
    )
