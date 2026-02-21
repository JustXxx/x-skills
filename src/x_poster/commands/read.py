"""
Read command - Read a single tweet's content from X.

Extracts:
- Tweet text
- Author name and handle
- Timestamp
- Media (images/videos)
- Engagement metrics (likes, retweets, replies, views)
- Quoted tweet (if any)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import click

from ..chrome import ChromeSession, launch_chrome
from ..page import PageHelper

logger = logging.getLogger(__name__)

# Selectors for tweet detail page
TWEET_TEXT = '[data-testid="tweetText"]'
USER_NAME = '[data-testid="User-Name"]'
TWEET_ARTICLE = 'article[data-testid="tweet"]'
LOGIN_INDICATOR = '[data-testid="loginButton"], [href="/login"]'


def _normalize_url(url: str) -> str:
    """Normalize a tweet URL to full https format."""
    url = url.strip()
    if url.startswith("x.com") or url.startswith("twitter.com"):
        url = "https://" + url
    url = url.replace("twitter.com", "x.com")
    return url


async def _extract_tweet_data(page: PageHelper, index: int = 0) -> Dict[str, Any]:
    """Extract tweet data from the page.

    Args:
        page: PageHelper instance
        index: Which tweet article to extract (0 = first/main tweet)

    Returns:
        Dictionary with tweet data
    """
    js = """
    (function(idx) {
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        if (!articles[idx]) return null;
        const article = articles[idx];

        // Tweet text
        const textEl = article.querySelector('[data-testid="tweetText"]');
        const text = textEl ? textEl.innerText : '';

        // Author info
        const userEl = article.querySelector('[data-testid="User-Name"]');
        let displayName = '', handle = '';
        if (userEl) {
            const spans = userEl.querySelectorAll('span');
            for (const span of spans) {
                const t = span.textContent.trim();
                if (t.startsWith('@')) { handle = t; break; }
            }
            // Display name is usually the first text node
            const nameLink = userEl.querySelector('a');
            if (nameLink) {
                const nameSpans = nameLink.querySelectorAll('span');
                if (nameSpans.length > 0) displayName = nameSpans[0].textContent.trim();
            }
        }

        // Timestamp
        const timeEl = article.querySelector('time');
        const timestamp = timeEl ? timeEl.getAttribute('datetime') : '';
        const timeText = timeEl ? timeEl.textContent : '';

        // Images
        const images = [];
        const imgEls = article.querySelectorAll('[data-testid="tweetPhoto"] img');
        imgEls.forEach(function(img) {
            const src = img.getAttribute('src') || '';
            if (src && !src.includes('emoji') && !src.includes('profile_image')) {
                images.push(src);
            }
        });

        // Video
        const videoEls = article.querySelectorAll('video');
        const videos = [];
        videoEls.forEach(function(v) {
            const src = v.getAttribute('src') || v.querySelector('source')?.getAttribute('src') || '';
            if (src) videos.push(src);
        });

        // Engagement metrics
        const metrics = {};
        const replyBtn = article.querySelector('[data-testid="reply"]');
        const retweetBtn = article.querySelector('[data-testid="retweet"]');
        const likeBtn = article.querySelector('[data-testid="like"], [data-testid="unlike"]');
        const viewsEl = article.querySelector('a[href*="/analytics"]');

        // Parse localized number strings like "282.7万", "1.2亿", "3.5K", "1.2M"
        function parseLocalizedNum(str) {
            if (!str) return null;
            str = str.replace(/,/g, '');
            // Chinese: 万 = 10000, 亿 = 100000000
            var m = str.match(/(\\d+\\.?\\d*)\\s*万/);
            if (m) return String(Math.round(parseFloat(m[1]) * 10000));
            m = str.match(/(\\d+\\.?\\d*)\\s*亿/);
            if (m) return String(Math.round(parseFloat(m[1]) * 100000000));
            // English: K = 1000, M = 1000000, B = 1000000000
            m = str.match(/(\\d+\\.?\\d*)\\s*[Bb]/);
            if (m) return String(Math.round(parseFloat(m[1]) * 1000000000));
            m = str.match(/(\\d+\\.?\\d*)\\s*[Mm]/);
            if (m) return String(Math.round(parseFloat(m[1]) * 1000000));
            m = str.match(/(\\d+\\.?\\d*)\\s*[Kk]/);
            if (m) return String(Math.round(parseFloat(m[1]) * 1000));
            // Plain number
            m = str.match(/(\\d+)/);
            if (m) return m[1];
            return null;
        }

        function extractMetric(el) {
            if (!el) return null;
            var label = el.getAttribute('aria-label') || '';
            // aria-label usually has raw numbers like "1510 retweets" or "1510 次转推"
            var m = label.match(/(\\d[\\d,]*)/);
            if (m) return m[1].replace(/,/g, '');
            // Fallback to text content with localized parsing
            return parseLocalizedNum(el.textContent || '');
        }

        var v;
        v = extractMetric(replyBtn); if (v) metrics.replies = v;
        v = extractMetric(retweetBtn); if (v) metrics.retweets = v;
        v = extractMetric(likeBtn); if (v) metrics.likes = v;

        if (viewsEl) {
            // aria-label may have raw number like "2825805 次查看"
            var label = viewsEl.getAttribute('aria-label') || '';
            var vm = label.match(/(\\d[\\d,]*)/);
            if (vm) {
                metrics.views = vm[1].replace(/,/g, '');
            } else {
                // Fallback: text may be localized like "282.7万 查看"
                var parsed = parseLocalizedNum(viewsEl.textContent || '');
                if (parsed) metrics.views = parsed;
            }
        }

        // Quoted tweet
        let quoted = null;
        const quoteEl = article.querySelector('[data-testid="quoteTweet"]');
        if (quoteEl) {
            const qText = quoteEl.querySelector('[data-testid="tweetText"]');
            const qUser = quoteEl.querySelector('[data-testid="User-Name"]');
            quoted = {
                text: qText ? qText.innerText : '',
                author: qUser ? qUser.textContent.trim() : ''
            };
        }

        // Tweet URL (from permalink)
        let tweetUrl = '';
        const links = article.querySelectorAll('a[href*="/status/"]');
        for (const link of links) {
            const href = link.getAttribute('href') || '';
            if (href.match(/\\/status\\/\\d+$/)) {
                tweetUrl = 'https://x.com' + href;
                break;
            }
        }

        return {
            text: text,
            displayName: displayName,
            handle: handle,
            timestamp: timestamp,
            timeText: timeText,
            images: images,
            videos: videos,
            metrics: metrics,
            quoted: quoted,
            url: tweetUrl
        };
    })
    """

    result = await page.evaluate(f"({js})({index})")
    return result


def _format_tweet(data: Dict[str, Any]) -> str:
    """Format tweet data as readable text output."""
    if not data:
        return "No tweet data found."

    lines = []
    lines.append(f"👤 {data.get('displayName', '')} {data.get('handle', '')}")

    if data.get("timeText"):
        lines.append(f"🕐 {data['timeText']}  ({data.get('timestamp', '')})")

    lines.append("")
    lines.append(data.get("text", "(no text)"))
    lines.append("")

    # Media
    images = data.get("images", [])
    if images:
        lines.append(f"🖼️  {len(images)} image(s):")
        for i, url in enumerate(images, 1):
            lines.append(f"  [{i}] {url}")

    videos = data.get("videos", [])
    if videos:
        lines.append(f"🎬 {len(videos)} video(s):")
        for i, url in enumerate(videos, 1):
            lines.append(f"  [{i}] {url}")

    # Metrics
    metrics = data.get("metrics", {})
    if metrics:
        parts = []
        if "replies" in metrics:
            parts.append(f"💬 {metrics['replies']}")
        if "retweets" in metrics:
            parts.append(f"🔁 {metrics['retweets']}")
        if "likes" in metrics:
            parts.append(f"❤️  {metrics['likes']}")
        if "views" in metrics:
            parts.append(f"👁️  {metrics['views']}")
        if parts:
            lines.append("  ".join(parts))

    # Quoted tweet
    quoted = data.get("quoted")
    if quoted:
        lines.append("")
        lines.append(f"📎 Quoted: {quoted.get('author', '')}")
        lines.append(f"   {quoted.get('text', '')}")

    if data.get("url"):
        lines.append("")
        lines.append(f"🔗 {data['url']}")

    return "\n".join(lines)


async def _run_read(
    tweet_url: str,
    output_json: bool,
    profile: Optional[str],
    chrome_path: Optional[str],
) -> None:
    """Core read implementation."""
    session: Optional[ChromeSession] = None

    try:
        url = _normalize_url(tweet_url)
        click.echo(f"🔍 Reading tweet: {url}")

        session = await launch_chrome(
            url=url,
            profile_dir=profile,
            chrome_path=chrome_path,
        )

        page = PageHelper(session.cdp, session.session_id)

        # Wait for tweet content to load
        click.echo("⏳ Loading tweet...")
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
            raise TimeoutError("Tweet page did not load.")

        # Wait for content to render
        await asyncio.sleep(2.0)

        # Extract tweet data
        data = await _extract_tweet_data(page, index=0)

        if not data:
            click.echo("❌ Could not extract tweet data.", err=True)
            return

        if output_json:
            click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            click.echo("")
            click.echo(_format_tweet(data))

    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise
    finally:
        if session:
            await session.cleanup()


@click.command("read")
@click.argument("tweet_url")
@click.option("--json", "-j", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def read_tweet(ctx: click.Context, tweet_url: str, output_json: bool) -> None:
    """Read a single tweet's content.

    Examples:

        xpost read 'https://x.com/user/status/123456'

        xpost read 'https://x.com/user/status/123456' --json
    """
    profile = ctx.obj.get("profile")
    chrome_path = ctx.obj.get("chrome_path")

    asyncio.run(_run_read(tweet_url, output_json, profile, chrome_path))
