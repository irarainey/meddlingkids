"""Pydantic models for browser session, navigation, and device configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class NavigationResult(BaseModel):
    """Result of a navigation attempt."""

    success: bool
    status_code: int | None
    status_text: str | None
    is_access_denied: bool
    error_message: str | None


class AccessDenialResult(BaseModel):
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


class DeviceConfig(BaseModel):
    """Device configuration for browser emulation."""

    user_agent: str
    viewport: dict[str, int]
    device_scale_factor: float
    is_mobile: bool
    has_touch: bool
