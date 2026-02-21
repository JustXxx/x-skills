"""
Video command - Create posts with video on X.

Uses DOM.setFileInputFiles to upload video directly,
then waits for video processing to complete.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import click

from ..chrome import ChromeSession, launch_chrome
from ..page import PageHelper

logger = logging.getLogger(__name__)

TWEET_EDITOR = '[data-testid="tweetTextarea_0"]'
TWEET_BUTTON = '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]'
LOGIN_INDICATOR = '[data-testid="loginButton"], [href="/login"]'
# File input for media upload
FILE_INPUT = 'input[data-testid="fileInput"], input[type="file"][accept*="video"]'
# Media toolbar button that triggers file input
MEDIA_BUTTON = '[data-testid="fileInput"]'

SUPPORTED_VIDEO_FORMATS = (".mp4", ".mov", ".webm")
MAX_VIDEO_WAIT = 180  # seconds


async def _wait_for_video_ready(page: PageHelper, timeout: float = MAX_VIDEO_WAIT) -> None:
    """Wait for video processing to complete.

    X processes uploaded videos server-side. We detect completion by
    checking if the tweet button becomes enabled/clickable.
    """
    click.echo(f"⏳ Waiting for video processing (up to {timeout}s)...")
    start = time.monotonic()

    while (time.monotonic() - start) < timeout:
        # Check if tweet button is enabled (video processing done)
        enabled = await page.is_element_enabled(
            '[data-testid="tweetButton"]'
        )
        if enabled:
            elapsed = time.monotonic() - start
            click.echo(f"✅ Video processing complete ({elapsed:.0f}s)")
            return

        # Also check for error indicators
        has_error = await page.evaluate(
            "!!document.querySelector('[data-testid=\"toast\"] [role=\"alert\"]')"
        )
        if has_error:
            error_text = await page.get_element_text('[data-testid="toast"]')
            raise RuntimeError(f"Video upload error: {error_text}")

        elapsed = time.monotonic() - start
        if int(elapsed) % 10 == 0 and elapsed > 1:
            click.echo(f"  ⏳ Still processing... ({elapsed:.0f}s)")

        await asyncio.sleep(2.0)

    raise TimeoutError(
        f"Video processing did not complete within {timeout}s. "
        "The video may be too large or in an unsupported format."
    )


async def _run_video(
    text: str,
    video_path: str,
    submit: bool,
    profile: Optional[str],
    chrome_path: Optional[str],
) -> None:
    """Core video post implementation."""
    session: Optional[ChromeSession] = None

    try:
        abs_video = os.path.abspath(video_path)
        if not os.path.isfile(abs_video):
            raise FileNotFoundError(f"Video not found: {abs_video}")

        ext = os.path.splitext(abs_video)[1].lower()
        if ext not in SUPPORTED_VIDEO_FORMATS:
            raise click.UsageError(
                f"Unsupported video format: {ext}. "
                f"Supported: {', '.join(SUPPORTED_VIDEO_FORMATS)}"
            )

        click.echo("🚀 Launching Chrome...")
        session = await launch_chrome(
            url="https://x.com/compose/post",
            profile_dir=profile,
            chrome_path=chrome_path,
        )

        page = PageHelper(session.cdp, session.session_id)

        # Wait for editor
        click.echo("⏳ Waiting for editor...")
        try:
            idx, _ = await page.wait_for_any_selector(
                [TWEET_EDITOR, LOGIN_INDICATOR], timeout=60.0
            )
            if idx == 1:
                click.echo("🔑 Please log in to X in Chrome...")
                await page.wait_for_selector(TWEET_EDITOR, timeout=300.0)
        except TimeoutError:
            raise TimeoutError("Editor did not appear. Is X accessible?")

        await asyncio.sleep(1.0)

        # Upload video via file input
        click.echo(f"🎬 Uploading video: {os.path.basename(video_path)}")

        # Find and set file input - X may have hidden file inputs
        # First try to make file input visible/accessible
        await page.evaluate(
            "(() => {"
            "  const inputs = document.querySelectorAll('input[type=\"file\"]');"
            "  inputs.forEach(i => { i.style.display = 'block'; i.style.opacity = '1'; });"
            "})()"
        )
        await asyncio.sleep(0.3)

        await page.upload_file(abs_video, 'input[type="file"]')

        # Wait for video processing
        await _wait_for_video_ready(page)

        # Type text after video is ready
        if text:
            click.echo(f"📝 Typing text ({len(text)} chars)...")
            await page.type_text(TWEET_EDITOR, text)
            await asyncio.sleep(0.5)

        # Submit or preview
        if submit:
            click.echo("📤 Submitting post...")
            await page.click_selector('[data-testid="tweetButton"]')
            await asyncio.sleep(2.0)
            click.echo("✅ Video post submitted!")
        else:
            click.echo(
                "👀 Preview mode: video and text filled in browser.\n"
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
@click.argument("text", default="")
@click.option(
    "--video", "-V",
    required=True,
    type=click.Path(exists=True),
    help="Video file to upload (MP4, MOV, WebM)",
)
@click.option("--submit", "-s", is_flag=True, help="Actually submit the post")
@click.pass_context
def video(ctx: click.Context, text: str, video: str, submit: bool) -> None:
    """Create a post with video on X.

    Examples:

        xpost video "Watch this!" --video clip.mp4

        xpost video "Amazing" -V recording.mov --submit
    """
    profile = ctx.obj.get("profile")
    chrome_path = ctx.obj.get("chrome_path")

    asyncio.run(_run_video(text, video, submit, profile, chrome_path))
