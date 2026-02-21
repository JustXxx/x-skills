"""
Quote command - Quote tweet (retweet with comment) on X.

Opens the target tweet, clicks the retweet button,
selects "Quote" from the dropdown, and types a comment.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import click

from ..chrome import ChromeSession, launch_chrome
from ..page import PageHelper

logger = logging.getLogger(__name__)

TWEET_EDITOR = '[data-testid="tweetTextarea_0"]'
RETWEET_BUTTON = '[data-testid="retweet"]'
UNRETWEET_BUTTON = '[data-testid="unretweet"]'
TWEET_BUTTON = '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]'
LOGIN_INDICATOR = '[data-testid="loginButton"], [href="/login"]'

# Multi-language quote menu item text patterns
QUOTE_PATTERNS = [
    "quote",           # English
    "引用",            # Chinese
    "引用ポスト",       # Japanese
    "인용",            # Korean
    "citar",           # Spanish/Portuguese
    "zitieren",        # German
    "citer",           # French
]


def _normalize_tweet_url(url: str) -> str:
    """Normalize a tweet URL to ensure it's valid.

    Accepts formats:
    - https://x.com/user/status/123456
    - https://twitter.com/user/status/123456
    - x.com/user/status/123456
    """
    url = url.strip()

    # Add scheme if missing
    if not url.startswith("http"):
        url = "https://" + url

    # Convert twitter.com to x.com
    url = url.replace("twitter.com", "x.com")

    # Validate format
    pattern = r"https://x\.com/\w+/status/\d+"
    if not re.match(pattern, url):
        raise click.UsageError(
            f"Invalid tweet URL: {url}\n"
            "Expected format: https://x.com/username/status/1234567890"
        )

    return url


async def _click_quote_option(page: PageHelper, timeout: float = 10.0) -> None:
    """Find and click the Quote option from the retweet dropdown.

    Handles multiple languages by searching for known quote text patterns.
    """
    import time

    start = time.monotonic()

    while (time.monotonic() - start) < timeout:
        # Look for menu items in the dropdown (try multiple selector strategies)
        found = await page.evaluate(
            """(() => {
                const patterns = """
            + repr([p.lower() for p in QUOTE_PATTERNS])
            + """;
                // Strategy 1: role=menuitem
                const items = document.querySelectorAll('[role="menuitem"]');
                for (const item of items) {
                    const text = (item.textContent || '').trim().toLowerCase();
                    for (const p of patterns) {
                        if (text.includes(p)) {
                            item.click();
                            return 'menuitem:' + text;
                        }
                    }
                }
                // Strategy 2: spans inside #layers with matching text
                const spans = document.querySelectorAll('#layers span');
                for (const span of spans) {
                    const text = (span.textContent || '').trim().toLowerCase();
                    for (const p of patterns) {
                        if (text === p) {
                            const clickTarget = span.closest('[role="menuitem"]') || span;
                            clickTarget.click();
                            return 'span:' + text;
                        }
                    }
                }
                return false;
            })()"""
        )
        if found:
            logger.debug("Clicked quote option (matched: %s)", found)
            return

        await asyncio.sleep(0.3)

    raise TimeoutError(
        "Could not find 'Quote' option in retweet dropdown. "
        "The tweet may have been deleted or restricted."
    )


async def _run_quote(
    tweet_url: str,
    comment: str,
    submit: bool,
    profile: Optional[str],
    chrome_path: Optional[str],
) -> None:
    """Core quote implementation."""
    session: Optional[ChromeSession] = None

    try:
        tweet_url = _normalize_tweet_url(tweet_url)

        click.echo("🚀 Launching Chrome...")
        session = await launch_chrome(
            url=tweet_url,
            profile_dir=profile,
            chrome_path=chrome_path,
        )

        page = PageHelper(session.cdp, session.session_id)

        # Wait for page to load - check for login or tweet content
        click.echo("⏳ Loading tweet...")
        try:
            idx, _ = await page.wait_for_any_selector(
                [RETWEET_BUTTON, UNRETWEET_BUTTON, LOGIN_INDICATOR],
                timeout=30.0,
            )
            if idx == 2:
                click.echo("🔑 Please log in to X in Chrome...")
                await page.wait_for_any_selector(
                    [RETWEET_BUTTON, UNRETWEET_BUTTON], timeout=300.0
                )
        except TimeoutError:
            raise TimeoutError(
                f"Tweet page did not load properly: {tweet_url}\n"
                "The tweet may have been deleted or you may be blocked."
            )

        await asyncio.sleep(1.0)

        # Click retweet button to open dropdown
        click.echo("🔁 Opening retweet menu...")
        rt_selector = RETWEET_BUTTON + ", " + UNRETWEET_BUTTON
        # Try CDP mouse click first, then JS click as fallback
        try:
            await page.click_selector(RETWEET_BUTTON)
        except (TimeoutError, RuntimeError):
            try:
                await page.click_selector(UNRETWEET_BUTTON)
            except (TimeoutError, RuntimeError):
                pass

        await asyncio.sleep(0.8)

        # Check if dropdown appeared; if not, retry with JS click
        has_menu = await page.evaluate(
            'document.querySelectorAll(\'[role="menuitem"]\').length > 0'
        )
        if not has_menu:
            logger.debug("CDP click didn't open dropdown, retrying with JS click")
            await page.evaluate("""
                (() => {
                    const btn = document.querySelector('[data-testid="retweet"]')
                             || document.querySelector('[data-testid="unretweet"]');
                    if (btn) btn.click();
                })()
            """)
            await asyncio.sleep(0.8)

        # Select Quote from dropdown
        click.echo("💬 Selecting 'Quote'...")
        await _click_quote_option(page)

        # Wait for quote editor to appear
        await asyncio.sleep(1.5)
        await page.wait_for_selector(TWEET_EDITOR, timeout=10.0)

        # Type comment
        if comment:
            click.echo(f"📝 Typing comment ({len(comment)} chars)...")
            await page.type_text(TWEET_EDITOR, comment)
            await asyncio.sleep(0.5)

        # Submit or preview
        if submit:
            click.echo("📤 Submitting quote...")
            # Try CDP click first, then JS click as fallback
            try:
                await page.click_selector('[data-testid="tweetButton"]')
            except (TimeoutError, RuntimeError):
                logger.debug("CDP click on tweet button failed, using JS click")
                await page.evaluate("""
                    (() => {
                        const btn = document.querySelector('[data-testid="tweetButton"]')
                                 || document.querySelector('[data-testid="tweetButtonInline"]');
                        if (btn) btn.click();
                    })()
                """)
            await asyncio.sleep(3.0)
            click.echo("✅ Quote tweet submitted!")
        else:
            click.echo(
                "👀 Preview mode: quote filled in browser.\n"
                "   Review and click 'Post' manually, or re-run with --submit."
            )

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise
    finally:
        if session and submit:
            await session.cleanup()
        elif session:
            click.echo("💡 Chrome window left open for review.")
            try:
                while True:
                    await asyncio.sleep(1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                await session.cleanup()


@click.command()
@click.argument("tweet_url")
@click.argument("comment", default="")
@click.option("--submit", "-s", is_flag=True, help="Actually submit the quote")
@click.pass_context
def quote(ctx: click.Context, tweet_url: str, comment: str, submit: bool) -> None:
    """Quote (retweet with comment) a tweet on X.

    Examples:

        xpost quote "https://x.com/user/status/123" "Great thread!"

        xpost quote "x.com/user/status/123" "Interesting" --submit
    """
    if not tweet_url:
        raise click.UsageError("Please provide a tweet URL to quote.")

    profile = ctx.obj.get("profile")
    chrome_path = ctx.obj.get("chrome_path")

    asyncio.run(_run_quote(tweet_url, comment, submit, profile, chrome_path))
