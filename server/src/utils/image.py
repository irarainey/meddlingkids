"""Image processing utilities for screenshot optimization.

Centralises the PNG-to-JPEG conversion and downscaling logic
used by both the browser session (for client display) and the
agent base class (for LLM vision payloads).
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

# JPEG compression quality — 72 strikes a good balance
# between file-size and visual fidelity for analysis.
_JPEG_QUALITY = 72


# ── LLM vision settings ─────────────────────────────────────
# Smaller / more compressed images for LLM vision analysis.
# OpenAI's vision models resize to fit within 2048×2048 and
# then tile at 512 px.  768 px wide is enough for detecting
# buttons, text, and overlays while keeping the payload
# small and reducing upload / tokenization time.
_LLM_MAX_WIDTH = 768
_LLM_JPEG_QUALITY = 50


def optimize_png_to_jpeg(
    png_bytes: bytes,
    *,
    max_width: int = _MAX_WIDTH,
    quality: int = _JPEG_QUALITY,
) -> tuple[bytes, int, int]:
    """Downscale and convert a PNG screenshot to JPEG.

    Args:
        png_bytes: Raw PNG image bytes.
        max_width: Downscale images wider than this.
        quality: JPEG compression quality (1-95).

    Returns:
        Tuple of (jpeg_bytes, final_width, final_height).
    """
    img: Image.Image = Image.open(io.BytesIO(png_bytes))

    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize(
            (max_width, int(img.height * ratio)),
            Image.Resampling.LANCZOS,
        )

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), img.width, img.height


def png_to_data_url(png_bytes: bytes) -> str:
    """Convert raw PNG bytes to an optimised JPEG data-URL string.

    Convenience wrapper that downscales, compresses, and
    base64-encodes the result.  Used for **client display**.

    Args:
        png_bytes: Raw PNG screenshot bytes.

    Returns:
        A ``data:image/jpeg;base64,...`` string.
    """
    jpeg_bytes, _, _ = optimize_png_to_jpeg(png_bytes)
    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def optimize_for_llm(
    png_bytes: bytes,
) -> tuple[str, int]:
    """Aggressively optimize a screenshot for LLM vision.

    Uses a smaller maximum width and lower JPEG quality than
    the client-facing ``optimize_png_to_jpeg`` to minimise
    upload size and improve LLM response latency.

    Args:
        png_bytes: Raw PNG screenshot bytes.

    Returns:
        Tuple of (``data:image/jpeg;base64,...`` string,
        compressed byte count).
    """
    jpeg_bytes, _, _ = optimize_png_to_jpeg(
        png_bytes,
        max_width=_LLM_MAX_WIDTH,
        quality=_LLM_JPEG_QUALITY,
    )
    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
    return (
        f"data:image/jpeg;base64,{b64}",
        len(jpeg_bytes),
    )
