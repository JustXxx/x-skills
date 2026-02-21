"""
Article command - Publish long-form articles on X.

Converts Markdown to HTML and publishes as an X Article:
1. Parse Markdown with frontmatter
2. Open X Articles editor
3. Upload cover image
4. Fill title
5. Paste HTML content into DraftJS editor
6. Replace image placeholders with actual images
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import click

from ..chrome import ChromeSession, launch_chrome
from ..clipboard import copy_html, copy_image
from ..markdown_converter import ParsedArticle, parse_markdown
from ..page import PageHelper
from ..paste import send_paste

logger = logging.getLogger(__name__)

# X Article editor selectors
ARTICLE_EDITOR = '[data-testid="editor"]'  # DraftJS editor
ARTICLE_TITLE = '[data-testid="articleTitle"], [placeholder*="Title"], [data-placeholder*="Title"]'
ARTICLE_BODY = '[data-contents="true"], [contenteditable="true"]'
COVER_UPLOAD_BUTTON = '[data-testid="addCoverPhoto"], [aria-label*="cover"], [aria-label*="Cover"]'
COVER_APPLY_BUTTON = '[data-testid="applyButton"], [data-testid="confirmationSheetConfirm"]'
PUBLISH_BUTTON = '[data-testid="publishButton"], [data-testid="tweetButton"]'
LOGIN_INDICATOR = '[data-testid="loginButton"], [href="/login"]'
WRITE_BUTTON = '[data-testid="write"], [href*="/compose/articles"]'


async def _wait_for_article_editor(page: PageHelper, timeout: float = 60.0) -> None:
    """Wait for the article editor to be ready."""
    try:
        idx, selector = await page.wait_for_any_selector(
            [ARTICLE_BODY, ARTICLE_TITLE, LOGIN_INDICATOR],
            timeout=timeout,
        )
        if selector == LOGIN_INDICATOR or idx == 2:
            click.echo("🔑 Please log in to X in Chrome...")
            await page.wait_for_any_selector(
                [ARTICLE_BODY, ARTICLE_TITLE], timeout=300.0
            )
            click.echo("✅ Login detected!")
    except TimeoutError:
        raise TimeoutError(
            "Article editor did not load. Make sure you have X Premium "
            "(required for Articles feature)."
        )


async def _upload_cover_image(page: PageHelper, cover_path: str) -> None:
    """Upload cover image for the article."""
    if not os.path.isfile(cover_path):
        click.echo(f"⚠️  Cover image not found: {cover_path}, skipping")
        return

    click.echo(f"🖼️  Uploading cover image: {os.path.basename(cover_path)}")

    # Try clicking the cover upload button
    try:
        await page.click_selector(COVER_UPLOAD_BUTTON, timeout=5.0)
        await asyncio.sleep(1.0)

        # Upload via file input
        await page.upload_file(cover_path, 'input[type="file"]')
        await asyncio.sleep(2.0)

        # Click Apply/Confirm if present
        try:
            await page.click_selector(COVER_APPLY_BUTTON, timeout=5.0)
            await asyncio.sleep(1.0)
        except (TimeoutError, RuntimeError):
            pass  # Apply button may not appear if auto-applied

        click.echo("✅ Cover image uploaded")

    except TimeoutError:
        # Fallback: try clipboard paste for cover
        click.echo("  ⚠️  Cover button not found, trying clipboard paste...")
        copy_image(cover_path)
        await asyncio.sleep(0.3)
        send_paste()
        await asyncio.sleep(2.0)


async def _fill_title(page: PageHelper, title: str) -> None:
    """Fill in the article title."""
    if not title:
        return

    click.echo(f"📝 Setting title: {title[:50]}{'...' if len(title) > 50 else ''}")

    # Try known title selectors
    title_selectors = [
        '[data-testid="articleTitle"]',
        '[placeholder*="Title"]',
        '[data-placeholder*="Title"]',
        '[role="textbox"]:first-of-type',
    ]

    for selector in title_selectors:
        try:
            await page.wait_for_selector(selector, timeout=3.0)
            await page.type_text(selector, title)
            return
        except (TimeoutError, RuntimeError):
            continue

    # Fallback: use keyboard input
    click.echo("  ⚠️  Title field not found via selector, trying keyboard input...")
    await page.evaluate(
        "(() => {"
        "  const el = document.querySelector('[contenteditable=\"true\"]');"
        "  if (el) { el.focus(); }"
        "})()"
    )
    # Use Input.insertText CDP method for more reliable typing
    await page.cdp.send(
        "Input.insertText",
        {"text": title},
        session_id=page.session_id,
    )


async def _paste_html_content(page: PageHelper, html: str) -> bool:
    """Paste HTML content into the article editor.

    Tries multiple strategies:
    1. ClipboardEvent dispatch
    2. System clipboard + osascript paste
    3. execCommand('insertHTML')
    """
    click.echo("📄 Pasting article content...")

    # Strategy 1: ClipboardEvent (best for DraftJS)
    body_selectors = [
        '[data-contents="true"]',
        '[contenteditable="true"]',
        '.DraftEditor-root',
        '[role="textbox"]',
    ]

    for selector in body_selectors:
        try:
            success = await page.paste_html_content(html, selector)
            if success:
                # Verify content was actually inserted
                await asyncio.sleep(1.0)
                text_length = await page.evaluate(
                    f"(() => {{"
                    f"  const el = document.querySelector('{selector}');"
                    f"  return el ? el.textContent.length : 0;"
                    f"}})()"
                )
                if text_length and text_length > 10:
                    click.echo("✅ Content pasted via ClipboardEvent")
                    return True
        except (TimeoutError, RuntimeError):
            continue

    # Strategy 2: System clipboard paste
    click.echo("  ⚠️  ClipboardEvent failed, trying system clipboard paste...")
    copy_html(html)
    await asyncio.sleep(0.5)

    # Focus the editor
    for selector in body_selectors:
        try:
            await page.evaluate(
                f"(() => {{"
                f"  const el = document.querySelector('{selector}');"
                f"  if (el) el.focus();"
                f"}})()"
            )
            break
        except RuntimeError:
            continue

    send_paste()
    await asyncio.sleep(2.0)

    # Check if content appeared
    for selector in body_selectors:
        try:
            text_length = await page.evaluate(
                f"(() => {{"
                f"  const el = document.querySelector('{selector}');"
                f"  return el ? el.textContent.length : 0;"
                f"}})()"
            )
            if text_length and text_length > 10:
                click.echo("✅ Content pasted via system clipboard")
                return True
        except RuntimeError:
            continue

    click.echo(
        "⚠️  Auto-paste failed. HTML has been copied to your clipboard.\n"
        "   Please paste it manually into the editor (Cmd+V)."
    )
    return False


async def _replace_image_placeholders(
    page: PageHelper, article: ParsedArticle
) -> None:
    """Replace XIMGPH_N placeholders with actual images.

    For each placeholder:
    1. Find the placeholder text in the editor
    2. Select it
    3. Delete it
    4. Paste the image via clipboard
    """
    if not article.image_placeholders:
        return

    click.echo(f"🖼️  Replacing {len(article.image_placeholders)} image placeholder(s)...")

    for placeholder, image_path in article.image_placeholders.items():
        if not os.path.isfile(image_path):
            click.echo(f"  ⚠️  Image not found: {image_path}, skipping {placeholder}")
            continue

        click.echo(f"  📎 {placeholder} -> {os.path.basename(image_path)}")

        # Find and select the placeholder text
        selected = await page.evaluate(
            f"(() => {{"
            f"  const walker = document.createTreeWalker("
            f"    document.querySelector('[contenteditable=\"true\"]') || document.body,"
            f"    NodeFilter.SHOW_TEXT"
            f"  );"
            f"  while (walker.nextNode()) {{"
            f"    const idx = walker.currentNode.textContent.indexOf('[{placeholder}]');"
            f"    if (idx >= 0) {{"
            f"      const range = document.createRange();"
            f"      range.setStart(walker.currentNode, idx);"
            f"      range.setEnd(walker.currentNode, idx + {len(f'[{placeholder}]')});"
            f"      const sel = window.getSelection();"
            f"      sel.removeAllRanges();"
            f"      sel.addRange(range);"
            f"      return true;"
            f"    }}"
            f"  }}"
            f"  return false;"
            f"}})()"
        )

        if not selected:
            click.echo(f"  ⚠️  Placeholder [{placeholder}] not found in editor")
            continue

        # Delete selected text
        await page.evaluate("document.execCommand('delete', false)")
        await asyncio.sleep(0.3)

        # Paste image
        copy_image(image_path)
        await asyncio.sleep(0.3)
        send_paste()
        await asyncio.sleep(1.5)

    click.echo("✅ Image placeholders replaced")


async def _run_article(
    markdown_path: str,
    cover: Optional[str],
    title: Optional[str],
    submit: bool,
    profile: Optional[str],
    chrome_path: Optional[str],
) -> None:
    """Core article implementation."""
    session: Optional[ChromeSession] = None

    try:
        # Parse Markdown
        click.echo(f"📖 Parsing Markdown: {markdown_path}")
        article = parse_markdown(markdown_path, title, cover)

        if not article.title:
            click.echo("⚠️  No title found. Use --title or add 'title:' to frontmatter.")

        click.echo(f"  Title: {article.title or '(none)'}")
        click.echo(f"  Cover: {article.cover_image or '(none)'}")
        click.echo(f"  Images: {len(article.images)}")
        click.echo(f"  HTML length: {len(article.html)} chars")

        # Launch Chrome
        click.echo("🚀 Launching Chrome...")
        session = await launch_chrome(
            url="https://x.com/i/articles/create",
            profile_dir=profile,
            chrome_path=chrome_path,
        )

        page = PageHelper(session.cdp, session.session_id)

        # Wait for editor
        click.echo("⏳ Waiting for article editor...")
        await _wait_for_article_editor(page)
        await asyncio.sleep(2.0)

        # Upload cover image
        if article.cover_image:
            await _upload_cover_image(page, article.cover_image)

        # Fill title
        if article.title:
            await _fill_title(page, article.title)
            await asyncio.sleep(0.5)

        # Tab to body / click body
        await page.evaluate(
            "(() => {"
            "  const body = document.querySelector('[data-contents=\"true\"]') "
            "    || document.querySelector('[contenteditable=\"true\"]:not(:first-child)');"
            "  if (body) body.focus();"
            "})()"
        )
        await asyncio.sleep(0.5)

        # Paste HTML content
        await _paste_html_content(page, article.html)
        await asyncio.sleep(1.0)

        # Replace image placeholders
        await _replace_image_placeholders(page, article)

        # Submit or preview
        if submit:
            click.echo("📤 Publishing article...")
            try:
                await page.click_selector(PUBLISH_BUTTON, timeout=5.0)
            except TimeoutError:
                # Try alternative publish buttons
                await page.click_selector('[data-testid="tweetButton"]', timeout=5.0)
            await asyncio.sleep(3.0)
            click.echo("✅ Article published!")
        else:
            click.echo(
                "👀 Preview mode: article filled in browser.\n"
                "   Review and click 'Publish' manually, or re-run with --submit."
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
@click.argument("markdown_path", type=click.Path(exists=True))
@click.option("--cover", "-c", type=click.Path(), help="Cover image file path")
@click.option("--title", "-t", help="Article title (overrides frontmatter)")
@click.option("--submit", "-s", is_flag=True, help="Actually publish the article")
@click.pass_context
def article(
    ctx: click.Context,
    markdown_path: str,
    cover: Optional[str],
    title: Optional[str],
    submit: bool,
) -> None:
    """Publish a long-form article on X from Markdown.

    Requires X Premium subscription for the Articles feature.

    The Markdown file can include YAML frontmatter:

    \b
        ---
        title: My Article Title
        cover_image: ./cover.jpg
        ---

    Examples:

        xpost article my-post.md

        xpost article my-post.md --cover hero.jpg --title "My Title"

        xpost article my-post.md --submit
    """
    profile = ctx.obj.get("profile")
    chrome_path = ctx.obj.get("chrome_path")

    asyncio.run(_run_article(markdown_path, cover, title, submit, profile, chrome_path))
