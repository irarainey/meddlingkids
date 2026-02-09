"""
Error handling utilities for consistent error message extraction.
"""


def get_error_message(error: BaseException | object) -> str:
    """
    Safely extract an error message from an unknown error type.
    """
    if isinstance(error, Exception):
        return str(error)
    return "Unknown error"
