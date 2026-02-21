# x-poster Command Reference

## Overview

x-poster (`xpost`) is a CLI tool that controls X (Twitter) through a real Chrome browser using CDP (Chrome DevTools Protocol). It supports posting content and reading tweets.

**Binary**: `xpost` (installed globally via `pip install -e .`)

---

## Global Options

| Option | Env Var | Description |
|--------|---------|-------------|
| `--profile <dir>` | `XPOST_PROFILE` | Chrome profile directory (default: `~/.local/share/x-poster-profile`) |
| `--chrome-path <path>` | `CHROME_PATH` | Path to Chrome executable |
| `-v / --verbose` | — | Enable debug logging |
| `--version` | — | Show version |

---

## Publishing Commands

### `xpost post` — Text + Image Post

```
xpost post <text> [-i <image>]... [--submit]
```

| Argument/Option | Description |
|----------------|-------------|
| `text` | Tweet text content |
| `-i / --image <path>` | Image file path (max 4, repeat for multiple) |
| `--submit` | Actually publish (default: preview only) |

**Examples:**
```bash
xpost post 'Hello world!'
xpost post 'With images' -i photo1.jpg -i photo2.png
xpost post 'Publish it' --submit
```

### `xpost video` — Video Post

```
xpost video <text> -V <video_path> [--submit]
```

| Argument/Option | Description |
|----------------|-------------|
| `text` | Tweet text content |
| `-V / --video <path>` | Video file path (MP4/MOV/WebM, required) |
| `--submit` | Actually publish |

### `xpost quote` — Quote Tweet

```
xpost quote <tweet_url> <text> [--submit]
```

| Argument/Option | Description |
|----------------|-------------|
| `tweet_url` | URL of the tweet to quote |
| `text` | Quote comment text |
| `--submit` | Actually publish |

### `xpost article` — Long-form Article

```
xpost article <markdown_file> [--title <title>] [--cover <image>] [--submit]
```

| Argument/Option | Description |
|----------------|-------------|
| `markdown_file` | Path to Markdown file |
| `--title <text>` | Article title (overrides frontmatter) |
| `--cover <image>` | Cover image path |
| `--submit` | Actually publish |

**Markdown frontmatter support:**
```yaml
---
title: My Article Title
subtitle: Optional subtitle
cover: /path/to/cover.jpg
---
```

### `xpost reply` — Reply to Tweet

```
xpost reply <tweet_url> <text> [--submit]
```

| Argument/Option | Description |
|----------------|-------------|
| `tweet_url` | URL of the tweet to reply to |
| `text` | Reply text content |
| `--submit` | Actually publish |

**Examples:**
```bash
xpost reply 'https://x.com/user/status/123' 'Great thread!'
xpost reply 'https://x.com/user/status/123' 'Interesting' --submit
```

---

## Reading Commands

### `xpost read` — Read Single Tweet

```
xpost read <tweet_url> [--json]
```

| Argument/Option | Description |
|----------------|-------------|
| `tweet_url` | Full tweet URL (https://x.com/user/status/ID) |
| `-j / --json` | Output as JSON |

**Extracted data fields:**
- `text` — Tweet text
- `displayName` — Author display name
- `handle` — Author @handle
- `timestamp` — ISO 8601 timestamp
- `timeText` — Localized time display
- `images` — Array of image URLs
- `videos` — Array of video URLs
- `metrics` — Object with `replies`, `retweets`, `likes`, `views`
- `quoted` — Quoted tweet data (if any): `{text, author}`
- `url` — Canonical tweet URL

### `xpost timeline` — Read User Timeline

```
xpost timeline <user_url> [-n <count>] [--json]
```

| Argument/Option | Description |
|----------------|-------------|
| `user_url` | User profile URL, `@handle`, or `handle` |
| `-n / --count <N>` | Number of tweets (default: 10, max: 200) |
| `-j / --json` | Output as JSON array |

**Input formats accepted:**
- `@elonmusk`
- `elonmusk`
- `https://x.com/elonmusk`

### `xpost search` — Search Tweets

```
xpost search <query> [-n <count>] [--latest] [--json]
```

| Argument/Option | Description |
|----------------|-------------|
| `query` | Search query string |
| `-n / --count <N>` | Number of results (default: 10, max: 200) |
| `-l / --latest` | Sort by Latest (default: Top/relevance) |
| `-j / --json` | Output as JSON array |

**Search operators:**
- `from:username` — Tweets from specific user
- `to:username` — Replies to specific user
- `#hashtag` — Hashtag search
- `"exact phrase"` — Exact phrase match
- `since:2025-01-01` / `until:2025-12-31` — Date range
- `filter:media` — Only tweets with media
- `lang:en` — Language filter

---

## Utility Commands

### `xpost check` — Environment Check

```
xpost check
```

Checks: Chrome installation, Profile directory, Python version, Dependencies, Swift compiler, Accessibility permissions, Clipboard binary, Chrome instances.

---

## Multi-Account Support

Use `--profile` to maintain separate Chrome profiles for different X accounts:

```bash
xpost --profile ~/.x-poster/account-a post 'from A'
xpost --profile ~/.x-poster/account-b post 'from B'
```

First run with a new profile requires manual login in the Chrome window.

---

## JSON Output Schema

All reading commands support `--json` output. Single tweet returns an object, timeline/search return an array of objects. Each tweet object follows this schema:

```json
{
  "text": "string",
  "displayName": "string",
  "handle": "@string",
  "timestamp": "ISO8601",
  "timeText": "string",
  "images": ["url", ...],
  "videos": ["url", ...],
  "metrics": {
    "replies": "string_number",
    "retweets": "string_number",
    "likes": "string_number",
    "views": "string_number"
  },
  "quoted": null | {"text": "string", "author": "string"},
  "url": "https://x.com/user/status/ID"
}
```
