"""
Markdown to HTML converter for X Articles.

Features:
- YAML frontmatter parsing (title, cover_image)
- Custom heading mapping (H1 as title, H2-H6 as h2)
- Code block syntax highlighting via Pygments
- Image placeholder replacement (XIMGPH_N pattern)
- Remote image download and caching
- CJK-friendly text processing
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

try:
    import markdown
    from markdown.extensions import fenced_code
    from markdown.extensions.codehilite import CodeHiliteExtension
except ImportError:
    markdown = None

try:
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name, guess_lexer
except ImportError:
    highlight = None

logger = logging.getLogger(__name__)

IMAGE_CACHE_DIR = os.path.expanduser("~/.cache/x-poster/images")
IMAGE_PLACEHOLDER_PATTERN = "XIMGPH_{index}"


@dataclass
class ParsedArticle:
    """Result of parsing a Markdown article.

    Attributes:
        title: Article title (from frontmatter or first H1)
        cover_image: Path to cover image (from frontmatter)
        html: Rendered HTML content
        images: Ordered list of image paths found in the article
        image_placeholders: Map of placeholder string -> image path
    """
    title: str = ""
    cover_image: Optional[str] = None
    html: str = ""
    images: List[str] = field(default_factory=list)
    image_placeholders: Dict[str, str] = field(default_factory=dict)


def _parse_frontmatter(content: str) -> Tuple[dict, str]:
    """Extract YAML frontmatter from markdown content.

    Args:
        content: Raw markdown string

    Returns:
        Tuple of (frontmatter_dict, remaining_content)
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    try:
        fm = yaml.safe_load(parts[1])
        if not isinstance(fm, dict):
            return {}, content
        return fm, parts[2].strip()
    except yaml.YAMLError:
        return {}, content


def _download_image(url: str, base_dir: str) -> str:
    """Download a remote image and cache it locally.

    Args:
        url: Image URL
        base_dir: Base directory for relative path resolution

    Returns:
        Local path to the downloaded image
    """
    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

    # Generate cache filename from URL hash
    url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
    ext = os.path.splitext(url.split("?")[0])[1] or ".png"
    cache_path = os.path.join(IMAGE_CACHE_DIR, f"{url_hash}{ext}")

    if os.path.isfile(cache_path):
        return cache_path

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(cache_path, "wb") as f:
                f.write(resp.read())
        logger.info("Downloaded image: %s -> %s", url, cache_path)
        return cache_path
    except Exception as e:
        logger.warning("Failed to download image %s: %s", url, e)
        return url


def _resolve_image_path(src: str, base_dir: str) -> str:
    """Resolve an image source to an absolute local path.

    Handles:
    - Absolute paths
    - Relative paths (resolved against base_dir)
    - HTTP/HTTPS URLs (downloaded and cached)
    """
    if src.startswith(("http://", "https://")):
        return _download_image(src, base_dir)

    if os.path.isabs(src):
        return src

    return os.path.abspath(os.path.join(base_dir, src))


def _process_images(html: str, base_dir: str) -> Tuple[str, List[str], Dict[str, str]]:
    """Replace images in HTML with placeholders.

    Scans for <img> tags, replaces them with XIMGPH_N placeholders,
    and returns a mapping of placeholders to image paths.

    Args:
        html: HTML string with <img> tags
        base_dir: Base directory for relative image resolution

    Returns:
        Tuple of (modified_html, image_list, placeholder_map)
    """
    images = []
    placeholders = {}
    img_pattern = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*/?>', re.IGNORECASE)

    def replace_img(match: re.Match) -> str:
        src = match.group(1)
        local_path = _resolve_image_path(src, base_dir)
        index = len(images)
        placeholder = IMAGE_PLACEHOLDER_PATTERN.format(index=index)
        images.append(local_path)
        placeholders[placeholder] = local_path
        return f'<p>[{placeholder}]</p>'

    processed = img_pattern.sub(replace_img, html)
    return processed, images, placeholders


def _highlight_code_block(code: str, language: str) -> str:
    """Highlight a code block using Pygments.

    Falls back to plain <pre><code> if Pygments is unavailable.
    """
    if highlight is None:
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<blockquote><pre><code class="language-{language}">{escaped}</code></pre></blockquote>'

    try:
        if language:
            lexer = get_lexer_by_name(language)
        else:
            lexer = guess_lexer(code)
    except Exception:
        from pygments.lexers import TextLexer
        lexer = TextLexer()

    formatter = HtmlFormatter(nowrap=True, style="monokai")
    highlighted = highlight(code, lexer, formatter)
    return f'<blockquote><pre>{highlighted}</pre></blockquote>'


def _custom_render_markdown(md_content: str) -> str:
    """Render Markdown to HTML with custom rules for X Articles.

    Custom rules:
    - H1 is extracted as title (not rendered)
    - H2-H6 are all rendered as <h2>
    - Code blocks are wrapped in <blockquote> with syntax highlighting
    """
    if markdown is None:
        raise RuntimeError(
            "markdown package not installed. Run: pip install markdown"
        )

    # Pre-process: extract H1 as title
    lines = md_content.split("\n")
    processed_lines = []
    extracted_title = ""

    for line in lines:
        if line.startswith("# ") and not line.startswith("## ") and not extracted_title:
            extracted_title = line[2:].strip()
            continue  # Skip H1 in output
        processed_lines.append(line)

    processed_md = "\n".join(processed_lines)

    # Convert markdown to HTML
    extensions = ["fenced_code", "tables", "nl2br"]
    html = markdown.markdown(processed_md, extensions=extensions)

    # Post-process: normalize headings (h2-h6 -> h2)
    for level in range(6, 1, -1):
        html = html.replace(f"<h{level}>", "<h2>").replace(f"</h{level}>", "</h2>")

    # Post-process: wrap code blocks in blockquote
    code_block_pattern = re.compile(
        r'<pre><code\s*(?:class="language-(\w+)")?\s*>(.*?)</code></pre>',
        re.DOTALL,
    )

    def replace_code(match: re.Match) -> str:
        language = match.group(1) or ""
        code = match.group(2)
        # Unescape HTML entities in code
        code = (
            code.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        return _highlight_code_block(code, language)

    html = code_block_pattern.sub(replace_code, html)

    return html, extracted_title


def parse_markdown(
    md_path: str,
    title_override: Optional[str] = None,
    cover_override: Optional[str] = None,
) -> ParsedArticle:
    """Parse a Markdown file into a structured article for X.

    Args:
        md_path: Path to the Markdown file
        title_override: Override title from CLI argument
        cover_override: Override cover image from CLI argument

    Returns:
        ParsedArticle with all fields populated

    Raises:
        FileNotFoundError: If markdown file doesn't exist
    """
    md_path = os.path.abspath(md_path)
    if not os.path.isfile(md_path):
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    base_dir = os.path.dirname(md_path)

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse frontmatter
    frontmatter, md_content = _parse_frontmatter(content)

    # Render markdown to HTML
    html, h1_title = _custom_render_markdown(md_content)

    # Determine title (priority: CLI override > frontmatter > H1)
    title = title_override or frontmatter.get("title", "") or h1_title

    # Determine cover image
    cover = cover_override or frontmatter.get("cover_image", "") or frontmatter.get("cover", "")
    if cover:
        cover = _resolve_image_path(cover, base_dir)

    # Process images -> placeholders
    html, images, placeholders = _process_images(html, base_dir)

    return ParsedArticle(
        title=title,
        cover_image=cover if cover else None,
        html=html,
        images=images,
        image_placeholders=placeholders,
    )
