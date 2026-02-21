"""
Search command - Search tweets on X.

Supports:
- Keyword search
- Collecting N results with auto-scrolling
- JSON or text output
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from typing import Any, Dict, List, Optional

import click

from ..chrome import ChromeSession, launch_chrome
from ..page import PageHelper
from .read import _extract_tweet_data, _format_tweet, LOGIN_INDICATOR, TWEET_ARTICLE

logger = logging.getLogger(__name__)


def _build_search_url(query: str, search_type: str = "Latest") -> str:
    """Build X search URL.

    Args:
        query: Search keyword
        search_type: "Top" or "Latest"

    Returns:
        Full search URL
    """
    encoded = urllib.parse.quote(query)
    f_param = "live" if search_type == "Latest" else "top"
    return f"https://x.com/search?q={encoded}&src=typed_query&f={f_param}"


async def _scroll_and_collect_search(
    page: PageHelper,
    count: int,
    max_scroll_attempts: int = 50,
) -> List[Dict[str, Any]]:
    """Scroll search results and collect tweets."""
    collected = []
    seen_texts = set()
    scroll_attempts = 0
    last_count = 0
    stale_rounds = 0

    while len(collected) < count and scroll_attempts < max_scroll_attempts:
        total_on_page = await page.evaluate(
            "document.querySelectorAll('article[data-testid=\"tweet\"]').length"
        )

        if total_on_page is None:
            total_on_page = 0

        for i in range(total_on_page):
            if len(collected) >= count:
                break

            data = await _extract_tweet_data(page, index=i)
            if not data:
                continue

            key = (data.get("text", ""), data.get("handle", ""))
            if key in seen_texts:
                continue

            seen_texts.add(key)
            collected.append(data)

        if len(collected) >= count:
            break

        if len(collected) == last_count:
            stale_rounds += 1
            if stale_rounds >= 5:
                logger.info("No new results after %d scroll attempts, stopping", stale_rounds)
                break
        else:
            stale_rounds = 0
            last_count = len(collected)

        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await asyncio.sleep(1.5)
        scroll_attempts += 1

    return collected[:count]


async def _run_search(
    query: str,
    count: int,
    latest: bool,
    output_json: bool,
    profile: Optional[str],
    chrome_path: Optional[str],
) -> None:
    """Core search implementation."""
    session: Optional[ChromeSession] = None

    try:
        search_type = "Latest" if latest else "Top"
        url = _build_search_url(query, search_type)
        click.echo(f"🔍 Searching: '{query}' (type: {search_type}, count: {count})")

        session = await launch_chrome(
            url=url,
            profile_dir=profile,
            chrome_path=chrome_path,
        )

        page = PageHelper(session.cdp, session.session_id)

        # Wait for results to load
        click.echo("⏳ Loading search results...")
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
            click.echo("⚠️  No search results found or page did not load.")
            return

        await asyncio.sleep(2.0)

        # Collect results
        click.echo("📜 Scrolling and collecting results...")
        tweets = await _scroll_and_collect_search(page, count)

        click.echo(f"✅ Found {len(tweets)} tweet(s)")
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


@click.command("search")
@click.argument("query")
@click.option("--count", "-n", default=10, show_default=True, help="Number of tweets to collect")
@click.option("--latest", "-l", is_flag=True, help="Sort by Latest (default: Top)")
@click.option("--json", "-j", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def search(ctx: click.Context, query: str, count: int, latest: bool, output_json: bool) -> None:
    """Search tweets on X.

    Examples:

        xpost search 'Python programming' -n 5

        xpost search '#AI' -n 20 --latest

        xpost search 'from:elonmusk' -n 10 --json
    """
    if count < 1:
        raise click.UsageError("Count must be at least 1.")
    if count > 200:
        raise click.UsageError("Maximum 200 tweets per request.")

    profile = ctx.obj.get("profile")
    chrome_path = ctx.obj.get("chrome_path")

    asyncio.run(_run_search(query, count, latest, output_json, profile, chrome_path))
