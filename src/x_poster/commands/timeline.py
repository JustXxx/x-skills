"""
Timeline command - Read tweets from a user's timeline on X.

Supports:
- Reading N most recent tweets from a user profile
- Auto-scrolling to load more tweets
- JSON or text output
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import click

from ..chrome import ChromeSession, launch_chrome
from ..page import PageHelper
from .read import _extract_tweet_data, _format_tweet, LOGIN_INDICATOR, TWEET_ARTICLE

logger = logging.getLogger(__name__)


def _normalize_profile_url(url_or_handle: str) -> str:
    """Normalize a profile URL or handle to full URL."""
    s = url_or_handle.strip()
    # Just a handle like @username or username
    if not s.startswith("http"):
        s = s.lstrip("@")
        return f"https://x.com/{s}"
    s = s.replace("twitter.com", "x.com")
    if not s.startswith("https://"):
        s = "https://" + s.lstrip("http://")
    return s


async def _scroll_and_collect(
    page: PageHelper,
    count: int,
    max_scroll_attempts: int = 50,
) -> List[Dict[str, Any]]:
    """Scroll page and collect tweets.

    Args:
        page: PageHelper instance
        count: Number of tweets to collect
        max_scroll_attempts: Maximum scroll attempts to prevent infinite loop

    Returns:
        List of tweet data dictionaries
    """
    collected = []
    seen_texts = set()
    scroll_attempts = 0
    last_count = 0
    stale_rounds = 0

    while len(collected) < count and scroll_attempts < max_scroll_attempts:
        # Count available tweets on page
        total_on_page = await page.evaluate(
            "document.querySelectorAll('article[data-testid=\"tweet\"]').length"
        )

        if total_on_page is None:
            total_on_page = 0

        # Extract new tweets
        for i in range(total_on_page):
            if len(collected) >= count:
                break

            data = await _extract_tweet_data(page, index=i)
            if not data:
                continue

            # Deduplicate by text + handle
            key = (data.get("text", ""), data.get("handle", ""))
            if key in seen_texts:
                continue

            seen_texts.add(key)
            collected.append(data)

        if len(collected) >= count:
            break

        # Check if we're making progress
        if len(collected) == last_count:
            stale_rounds += 1
            if stale_rounds >= 5:
                logger.info("No new tweets after %d scroll attempts, stopping", stale_rounds)
                break
        else:
            stale_rounds = 0
            last_count = len(collected)

        # Scroll down
        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await asyncio.sleep(1.5)
        scroll_attempts += 1

    return collected[:count]


async def _run_timeline(
    user_url: str,
    count: int,
    output_json: bool,
    profile: Optional[str],
    chrome_path: Optional[str],
) -> None:
    """Core timeline implementation."""
    session: Optional[ChromeSession] = None

    try:
        url = _normalize_profile_url(user_url)
        click.echo(f"🔍 Reading timeline: {url} (up to {count} tweets)")

        session = await launch_chrome(
            url=url,
            profile_dir=profile,
            chrome_path=chrome_path,
        )

        page = PageHelper(session.cdp, session.session_id)

        # Wait for page to load
        click.echo("⏳ Loading timeline...")
        try:
            idx, selector = await page.wait_for_any_selector(
                [TWEET_ARTICLE, LOGIN_INDICATOR],
                timeout=30.0,
            )
            if idx == 1:
                click.echo(
                    "🔑 Login required! Please log in to X in the Chrome window..."
                )
                await page.wait_for_selector(TWEET_ARTICLE, timeout=300.0)
        except TimeoutError:
            raise TimeoutError("Timeline page did not load. User may not exist or account is suspended.")

        # Wait for initial render
        await asyncio.sleep(2.0)

        # Scroll and collect tweets
        click.echo("📜 Scrolling and collecting tweets...")
        tweets = await _scroll_and_collect(page, count)

        click.echo(f"✅ Collected {len(tweets)} tweet(s)")
        click.echo("")

        if output_json:
            click.echo(json.dumps(tweets, ensure_ascii=False, indent=2))
        else:
            for i, tweet in enumerate(tweets, 1):
                click.echo(f"{'─' * 50}")
                click.echo(f"[{i}/{len(tweets)}]")
                click.echo(_format_tweet(tweet))
                click.echo("")

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise
    finally:
        if session:
            await session.cleanup()


@click.command("timeline")
@click.argument("user_url")
@click.option("--count", "-n", default=10, show_default=True, help="Number of tweets to read")
@click.option("--json", "-j", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def timeline(ctx: click.Context, user_url: str, count: int, output_json: bool) -> None:
    """Read tweets from a user's timeline.

    USER_URL can be a full URL or just the handle (@username or username).

    Examples:

        xpost timeline '@elonmusk' -n 5

        xpost timeline 'https://x.com/elonmusk' -n 20

        xpost timeline 'elonmusk' -n 10 --json
    """
    if count < 1:
        raise click.UsageError("Count must be at least 1.")
    if count > 200:
        raise click.UsageError("Maximum 200 tweets per request.")

    profile = ctx.obj.get("profile")
    chrome_path = ctx.obj.get("chrome_path")

    asyncio.run(_run_timeline(user_url, count, output_json, profile, chrome_path))
