"""Pydantic models for browser session, navigation, and device configuration."""

from __future__ import annotations

from typing import Literal

import pydantic


class NavigationResult(pydantic.BaseModel):
    """Result of a navigation attempt."""

    success: bool
    status_code: int | None
    status_text: str | None
    is_access_denied: bool
    error_message: str | None


class AccessDenialResult(pydantic.BaseModel):
    """Result of an access denial check."""

    denied: bool
    reason: str | None


DeviceType = Literal[
    "iphone",
    "ipad",
    "android-phone",
    "android-tablet",
    "windows-chrome",
    "macos-safari",
]


class ViewportSize(pydantic.BaseModel):
    """Viewport dimensions for browser emulation."""

    width: int
    height: int


class DeviceConfig(pydantic.BaseModel):
    """Device configuration for browser emulation."""

    user_agent: str
    viewport: ViewportSize
    device_scale_factor: float
    is_mobile: bool
    has_touch: bool
