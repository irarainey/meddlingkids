"""
Device configuration profiles for browser emulation.
Defines user agents, viewports, and capabilities for different device types.
"""

from __future__ import annotations

from src.types.browser import DeviceConfig, ViewportSize

DEVICE_CONFIGS: dict[str, DeviceConfig] = {
    "iphone": DeviceConfig(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        viewport=ViewportSize(width=430, height=932),
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
    ),
    "ipad": DeviceConfig(
        user_agent="Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        viewport=ViewportSize(width=1024, height=1366),
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    ),
    "android-phone": DeviceConfig(
        user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Mobile Safari/537.36",
        viewport=ViewportSize(width=412, height=915),
        device_scale_factor=2.625,
        is_mobile=True,
        has_touch=True,
    ),
    "android-tablet": DeviceConfig(
        user_agent="Mozilla/5.0 (Linux; Android 14; Pixel Tablet) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Safari/537.36",
        viewport=ViewportSize(width=1280, height=800),
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    ),
    "windows-chrome": DeviceConfig(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport=ViewportSize(width=1920, height=1080),
        device_scale_factor=1,
        is_mobile=False,
        has_touch=False,
    ),
    "macos-safari": DeviceConfig(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        viewport=ViewportSize(width=1440, height=900),
        device_scale_factor=2,
        is_mobile=False,
        has_touch=False,
    ),
}


