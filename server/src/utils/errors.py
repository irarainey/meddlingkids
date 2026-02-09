"""
Error handling utilities for consistent error message extraction.
"""


def get_error_message(error: BaseException) -> str:
    """Extract a human-readable error message from an exception."""
    return str(error) or type(error).__name__
