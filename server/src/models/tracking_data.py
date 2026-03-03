"""Pydantic models for core tracking data: cookies, scripts, storage, and network requests."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pydantic

# ────────────────────────────────────────────────────────────
# Structural protocols for cookie / storage duck-typing
# ────────────────────────────────────────────────────────────


@runtime_checkable
class CookieLike(Protocol):
    """Structural protocol for cookie-like objects.

    Satisfied by :class:`TrackedCookie` and plain ``dict``
    objects with ``name`` and ``value`` keys (via the existing
    ``isinstance(cookie, dict)`` guard in consumer code).
    """

    @property
    def name(self) -> str: ...

    @property
    def value(self) -> str: ...


@runtime_checkable
class StorageItemLike(Protocol):
    """Structural protocol for storage-item-like objects.

    Satisfied by :class:`StorageItem` and plain ``dict``
    objects with ``key`` and ``value`` keys.
    """

    @property
    def key(self) -> str: ...

    @property
    def value(self) -> str: ...


# ────────────────────────────────────────────────────────────
# Concrete models
# ────────────────────────────────────────────────────────────


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


class CapturedStorage(pydantic.BaseModel):
    """localStorage and sessionStorage captured from the browser.

    Replaces the raw ``dict[str, list[StorageItem]]`` that was
    previously threaded through the pipeline with string keys
    ``"local_storage"`` and ``"session_storage"``.
    """

    local_storage: list[StorageItem] = pydantic.Field(default_factory=list)
    session_storage: list[StorageItem] = pydantic.Field(default_factory=list)


class NetworkRequest(pydantic.BaseModel):
    """Represents an HTTP network request made by the page."""

    url: str
    domain: str
    method: str
    resource_type: str
    is_third_party: bool
    timestamp: str
    status_code: int | None = None
    post_data: str | None = None
    pre_consent: bool = False
    initiator_domain: str | None = None
    redirected_from_url: str | None = None
