"""
Reply command - Reply to a tweet on X.

Opens the target tweet, clicks the reply area,
types a comment, and optionally submits.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import click

from ..chrome import ChromeSession, launch_chrome
from ..constants import LOGIN_INDICATOR, REPLY_BUTTON, TWEET_BUTTON, TWEET_EDITOR
from ..page import PageHelper
from ..utils import normalize_tweet_url

logger = logging.getLogger(__name__)


async def _click_reply_on_tweet(page: PageHelper) -> None:
    """Click the reply button on the main tweet (first article on the detail page)."""
    # On a tweet detail page, the first reply button belongs to the main tweet
    await page.evaluate("""
        (() => {
            const btn = document.querySelector('[data-testid="reply"]');
            if (btn) btn.click();
        })()
    """)


async def _run_reply(
    tweet_url: str,
    text: str,
    submit: bool,
    profile: Optional[str],
    chrome_path: Optional[str],
) -> None:
    """Core reply implementation."""
    session: Optional[ChromeSession] = None

    try:
        tweet_url = normalize_tweet_url(tweet_url)

        click.echo("🚀 Launching Chrome...")
        session = await launch_chrome(
            url=tweet_url,
            profile_dir=profile,
            chrome_path=chrome_path,
        )

        page = PageHelper(session.cdp, session.session_id)

        # Wait for page to load
        click.echo("⏳ Loading tweet...")
        try:
            idx, _ = await page.wait_for_any_selector(
                [REPLY_BUTTON, LOGIN_INDICATOR],
                timeout=30.0,
            )
            if idx == 1:
                click.echo("🔑 Please log in to X in Chrome...")
                await page.wait_for_selector(REPLY_BUTTON, timeout=300.0)
        except TimeoutError:
            raise TimeoutError(
                f"Tweet page did not load properly: {tweet_url}\n"
                "The tweet may have been deleted or you may be blocked."
            )

        await asyncio.sleep(1.0)

        # Click reply button to open the reply editor
        click.echo("💬 Opening reply editor...")
        await _click_reply_on_tweet(page)
        await asyncio.sleep(1.0)

        # Wait for the reply editor to appear
        await page.wait_for_selector(TWEET_EDITOR, timeout=10.0)

        # Type reply text
        if text:
            click.echo(f"📝 Typing reply ({len(text)} chars)...")
            await page.type_text(TWEET_EDITOR, text)
            await asyncio.sleep(0.5)

        # Submit or preview
        if submit:
            click.echo("📤 Submitting reply...")

            # Check if the tweet button is enabled before clicking
            is_enabled = await page.evaluate("""
                (() => {
                    const btn = document.querySelector('[data-testid="tweetButton"]')
                             || document.querySelector('[data-testid="tweetButtonInline"]');
                    if (!btn) return 'not_found';
                    return btn.disabled ? 'disabled' : 'enabled';
                })()
            """)
            logger.debug("Tweet button state before click: %s", is_enabled)

            if is_enabled == 'disabled':
                click.echo("⚠️  Tweet button is disabled, waiting for editor to settle...")
                await asyncio.sleep(2.0)

            # Try CDP click first, then JS click as fallback
            try:
                await page.click_selector(TWEET_BUTTON)
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
            click.echo("✅ Reply submitted!")
        else:
            click.echo(
                "👀 Preview mode: reply filled in browser.\n"
                "   Review and click 'Reply' manually, or re-run with --submit."
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
@click.argument("text")
@click.option("--submit", "-s", is_flag=True, help="Actually submit the reply")
@click.pass_context
def reply(ctx: click.Context, tweet_url: str, text: str, submit: bool) -> None:
    """Reply to a tweet on X.

    Examples:

        xpost reply "https://x.com/user/status/123" "Great thread!"

        xpost reply "x.com/user/status/123" "Interesting" --submit
    """
    if not tweet_url:
        raise click.UsageError("Please provide a tweet URL to reply to.")
    if not text:
        raise click.UsageError("Please provide reply text.")

    profile = ctx.obj.get("profile")
    chrome_path = ctx.obj.get("chrome_path")

    asyncio.run(_run_reply(tweet_url, text, submit, profile, chrome_path))
