"""
Error handling utilities for consistent error message extraction.
"""


def get_error_message(error: BaseException) -> str:
    """Extract a human-readable error message from an exception."""
    return str(error) or type(error).__name__


# Message returned to SSE clients in place of raw exception text.
_GENERIC_CLIENT_MESSAGE = "An internal error occurred during analysis. Please try again."


def get_safe_client_message(error: BaseException) -> str:
    """Return a sanitised error message safe for untrusted clients.

    Prevents leaking internal paths, hostnames or stack details.
    Only purpose-defined error types pass through; everything else
    maps to a generic message.
    """
    # Import here to avoid circular deps at module level.
    from src.utils.url import UnsafeURLError

    # Allow purpose-built user-facing error messages through.
    if isinstance(error, (UnsafeURLError, TimeoutError)):
        return str(error) or _GENERIC_CLIENT_MESSAGE

    return _GENERIC_CLIENT_MESSAGE
