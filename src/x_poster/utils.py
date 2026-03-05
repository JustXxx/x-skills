"""
Shared utility functions for x-poster.
"""

from __future__ import annotations

import re

import click


def normalize_tweet_url(url: str) -> str:
    """Normalize a tweet URL to ensure it's a valid https://x.com/... format.

    Accepts:
    - https://x.com/user/status/123456
    - https://twitter.com/user/status/123456
    - x.com/user/status/123456
    - twitter.com/user/status/123456

    Returns:
        Normalized URL string.

    Raises:
        click.UsageError: If the URL doesn't match expected tweet URL pattern.
    """
    url = url.strip()

    # Add scheme if missing
    if not url.startswith("http"):
        url = "https://" + url

    # Normalize twitter.com → x.com
    url = url.replace("twitter.com", "x.com")

    # Validate pattern
    pattern = r"https://x\.com/\w+/status/\d+"
    if not re.match(pattern, url):
        raise click.UsageError(
            f"Invalid tweet URL: {url}\n"
            "Expected format: https://x.com/username/status/1234567890"
        )
    return url


def normalize_profile_url(url_or_handle: str) -> str:
    """Normalize a profile URL or handle to full URL.

    Accepts:
    - @username / username
    - https://x.com/username
    - https://twitter.com/username
    - x.com/username

    Returns:
        Full https://x.com/<handle> URL.
    """
    s = url_or_handle.strip()

    # Just a handle
    if not s.startswith("http"):
        s = s.lstrip("@")
        return f"https://x.com/{s}"

    s = s.replace("twitter.com", "x.com")

    if not s.startswith("https://"):
        if s.startswith("http://"):
            s = "https://" + s[len("http://"):]
        else:
            s = "https://" + s

    return s
