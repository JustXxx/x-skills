"""
Post command - Create regular posts on X (text + images).

Supports:
- Pure text posts
- Text with up to 4 images
- Preview mode (default) and --submit for actual posting
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional, Tuple

import click

from ..chrome import ChromeSession, launch_chrome
from ..clipboard import copy_image
from ..page import PageHelper
from ..paste import send_paste

logger = logging.getLogger(__name__)

# X editor selectors
TWEET_EDITOR = '[data-testid="tweetTextarea_0"]'
TWEET_BUTTON = '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]'
LOGIN_INDICATOR = '[data-testid="loginButton"], [href="/login"]'
BLOB_IMAGE = 'img[src^="blob:"]'


async def _wait_for_editor_or_login(
    page: PageHelper, timeout: float = 60.0
) -> bool:
    """Wait for the tweet editor to appear, handling login redirect.

    Returns:
        True if editor is ready, False if login is needed
    """
    try:
        idx, selector = await page.wait_for_any_selector(
            [TWEET_EDITOR, LOGIN_INDICATOR],
            timeout=timeout,
        )
        if idx == 0:
            return True
        else:
            return False
    except TimeoutError:
        raise TimeoutError(
            "Neither tweet editor nor login page appeared. "
            "Check if X is accessible and Chrome is working."
        )


async def _paste_image(
    page: PageHelper, image_path: str, expected_count: int, timeout: float = 15.0
) -> None:
    """Copy image to clipboard and paste it into X editor.

    Args:
        page: PageHelper instance
        image_path: Path to the image file
        expected_count: Expected number of blob images after paste
        timeout: Timeout for paste verification
    """
    # Copy image to system clipboard via Swift
    copy_image(image_path)

    # Small delay to ensure clipboard is ready
    await asyncio.sleep(0.3)

    # Send real Cmd+V via osascript
    send_paste()

    # Wait and verify image upload
    start = time.monotonic()
    while (time.monotonic() - start) < timeout:
        count = await page.count_elements(BLOB_IMAGE)
        if count >= expected_count:
            logger.info("Image %d uploaded: %s", expected_count, os.path.basename(image_path))
            return
        await asyncio.sleep(0.5)

    current_count = await page.count_elements(BLOB_IMAGE)
    raise TimeoutError(
        f"Image paste verification failed. Expected {expected_count} images, "
        f"found {current_count} after {timeout}s. File: {image_path}"
    )


async def _run_post(
    text: str,
    images: Tuple[str, ...],
    submit: bool,
    profile: Optional[str],
    chrome_path: Optional[str],
) -> None:
    """Core post implementation."""
    session: Optional[ChromeSession] = None

    try:
        # Launch Chrome and open compose page
        click.echo("🚀 Launching Chrome...")
        session = await launch_chrome(
            url="https://x.com/compose/post",
            profile_dir=profile,
            chrome_path=chrome_path,
        )

        page = PageHelper(session.cdp, session.session_id)

        # Wait for editor
        click.echo("⏳ Waiting for editor...")
        editor_ready = await _wait_for_editor_or_login(page)

        if not editor_ready:
            click.echo(
                "🔑 Login required! Please log in to X in the Chrome window, "
                "then the script will continue automatically..."
            )
            await page.wait_for_selector(TWEET_EDITOR, timeout=300.0)
            click.echo("✅ Login detected!")

        # Give the editor a moment to fully initialize
        await asyncio.sleep(1.0)

        # Type text
        if text:
            click.echo(f"📝 Typing text ({len(text)} chars)...")
            await page.type_text(TWEET_EDITOR, text)
            await asyncio.sleep(0.5)

        # Upload images
        if images:
            click.echo(f"🖼️  Uploading {len(images)} image(s)...")
            for i, img_path in enumerate(images, 1):
                abs_path = os.path.abspath(img_path)
                if not os.path.isfile(abs_path):
                    raise FileNotFoundError(f"Image not found: {abs_path}")

                click.echo(f"  📎 Pasting image {i}/{len(images)}: {os.path.basename(img_path)}")
                await _paste_image(page, abs_path, expected_count=i)
                await asyncio.sleep(0.5)

        # Submit or preview
        if submit:
            click.echo("📤 Submitting post...")
            await page.click_selector(TWEET_BUTTON)
            await asyncio.sleep(2.0)
            click.echo("✅ Post submitted!")
        else:
            click.echo(
                "👀 Preview mode: content filled in browser.\n"
                "   Review and click 'Post' manually, or re-run with --submit."
            )

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise
    finally:
        if session and submit:
            # Only auto-cleanup if we submitted
            await session.cleanup()
        elif session:
            click.echo("💡 Chrome window left open for review. Press Ctrl+C to exit.")
            try:
                # Keep alive until user exits
                while True:
                    await asyncio.sleep(1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                await session.cleanup()


@click.command()
@click.argument("text", default="")
@click.option(
    "--image", "-i",
    multiple=True,
    type=click.Path(exists=True),
    help="Image file to attach (can be repeated, max 4)",
)
@click.option("--submit", "-s", is_flag=True, help="Actually submit the post")
@click.pass_context
def post(ctx: click.Context, text: str, image: Tuple[str, ...], submit: bool) -> None:
    """Create a regular post on X.

    Examples:

        xpost post "Hello world!"

        xpost post "Check this out" -i photo1.jpg -i photo2.png

        xpost post "Ready to go" -i image.jpg --submit
    """
    if not text and not image:
        raise click.UsageError("Please provide text and/or at least one image.")

    if len(image) > 4:
        raise click.UsageError("Maximum 4 images allowed per post.")

    profile = ctx.obj.get("profile")
    chrome_path = ctx.obj.get("chrome_path")

    asyncio.run(_run_post(text, image, submit, profile, chrome_path))
