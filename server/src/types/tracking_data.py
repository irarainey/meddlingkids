"""Pydantic models for core tracking data: cookies, scripts, storage, and network requests."""

from __future__ import annotations

import pydantic


class TrackedCookie(pydantic.BaseModel):
    """Represents a cookie captured from the browser context."""

    name: str
    value: str
    domain: str
    path: str
    expires: float
    http_only: bool
    secure: bool
    same_site: str
    timestamp: str


class TrackedScript(pydantic.BaseModel):
    """Represents a JavaScript script loaded by the page."""

    url: str
    domain: str
    timestamp: str = ""
    description: str | None = None
    resource_type: str = "script"
    group_id: str | None = None
    is_grouped: bool | None = None


class ScriptGroup(pydantic.BaseModel):
    """Represents a group of similar scripts."""

    id: str
    name: str
    description: str
    count: int
    example_urls: list[str]
    domain: str


class StorageItem(pydantic.BaseModel):
    """Represents an item stored in localStorage or sessionStorage."""

    key: str
    value: str
    timestamp: str


class NetworkRequest(pydantic.BaseModel):
    """Represents an HTTP network request made by the page."""

    url: str
    domain: str
    method: str
    resource_type: str
    is_third_party: bool
    timestamp: str
    status_code: int | None = None
