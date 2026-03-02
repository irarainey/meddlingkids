"""Tests for src.browser.device_configs — device profile catalogue."""

from __future__ import annotations

from typing import ClassVar

import pytest

from src.browser.device_configs import DEVICE_CONFIGS
from src.models.browser import DeviceConfig


class TestDeviceConfigs:
    EXPECTED_KEYS: ClassVar[set[str]] = {"iphone", "ipad", "android-phone", "android-tablet", "windows-chrome", "macos-safari"}

    def test_all_expected_keys_present(self) -> None:
        assert self.EXPECTED_KEYS.issubset(DEVICE_CONFIGS.keys())

    def test_values_are_device_configs(self) -> None:
        for key, cfg in DEVICE_CONFIGS.items():
            assert isinstance(cfg, DeviceConfig), f"{key} is not DeviceConfig"

    @pytest.mark.parametrize("key", EXPECTED_KEYS)
    def test_has_user_agent(self, key: str) -> None:
        assert DEVICE_CONFIGS[key].user_agent

    @pytest.mark.parametrize("key", EXPECTED_KEYS)
    def test_viewport_positive(self, key: str) -> None:
        vp = DEVICE_CONFIGS[key].viewport
        assert vp.width > 0
        assert vp.height > 0

    def test_mobile_devices_have_touch(self) -> None:
        for key in ("iphone", "ipad", "android-phone", "android-tablet"):
            cfg = DEVICE_CONFIGS[key]
            assert cfg.is_mobile is True
            assert cfg.has_touch is True

    def test_desktop_devices_no_touch(self) -> None:
        for key in ("windows-chrome", "macos-safari"):
            cfg = DEVICE_CONFIGS[key]
            assert cfg.is_mobile is False
            assert cfg.has_touch is False
