"""
Environment variable loader.
Strips whitespace and Windows carriage returns from all values.
This handles .env files saved on Windows with CRLF line endings.
"""

import os


def env(key: str, default: str = "") -> str:
    """
    Get an environment variable, stripping all whitespace and
    Windows carriage returns (\r) that sneak in from CRLF .env files.
    """
    return os.environ.get(key, default).strip().strip("\r\n")


def env_bool(key: str) -> bool:
    return bool(env(key))
