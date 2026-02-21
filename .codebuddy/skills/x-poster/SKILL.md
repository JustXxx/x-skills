---
name: x-poster
description: "X (Twitter) automation skill for posting and reading tweets via Chrome CDP. This skill should be used when the user wants to interact with X or Twitter, including posting tweets (text, images, video), quoting tweets, publishing long-form articles, reading individual tweets, browsing user timelines, or searching tweets. It operates through a real Chrome browser using the Chrome DevTools Protocol, requiring no API keys."
---

# x-poster: X (Twitter) Automation Skill

## Purpose

Provide the ability to post content to and read content from X (Twitter) using a real Chrome browser controlled via CDP (Chrome DevTools Protocol). This approach bypasses X API restrictions and requires no API keys — only a logged-in Chrome session.

## When to Use

Activate this skill when the user mentions any of the following:
- Posting, tweeting, or publishing to X / Twitter
- Replying to tweets
- Reading, fetching, or scraping tweets
- Browsing a user's Twitter/X timeline
- Searching tweets on X
- Quoting or retweeting
- Publishing articles or threads on X
- Any task involving `xpost` commands

## Prerequisites

- **macOS** (uses macOS-specific clipboard and keystroke APIs)
- **Python 3.9+** available as `python3`
- **Google Chrome** (or Chromium/Edge/Brave) installed
- **Accessibility permissions** granted to the terminal app (System Settings → Privacy & Security → Accessibility)

## Setup

Before first use, run the setup script to install dependencies:

```bash
bash <skill_base_dir>/scripts/setup.sh <project_root>
```

This installs the `xpost` CLI tool globally. Verify with:

```bash
xpost check
```

All checks should show ✅. If Accessibility permissions are missing, instruct the user to grant them.

### First Login

The first time any command runs, Chrome opens with a dedicated profile. The user must manually log in to X in the browser window. The session persists for future runs.

## Tool Location

After installation, `xpost` is available as a global command. Alternatively, use the wrapper script:
```bash
python3 <skill_base_dir>/scripts/xpost_run.py <command> [args...]
```

## Available Commands

### Publishing Commands

All publishing commands operate in **preview mode** by default (content is filled but not submitted). Add `--submit` to actually publish.

**IMPORTANT**: In zsh, use single quotes for text containing `!` to avoid shell expansion.

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `post <text>` | Post text + images | `-i <image>` (max 4), `--submit` |
| `video <text> -V <path>` | Post text + video | `-V <video>` (required), `--submit` |
| `quote <url> <text>` | Quote an existing tweet | `--submit` |
| `reply <url> <text>` | Reply to a tweet | `--submit` |
| `article <markdown>` | Publish long-form article | `--title`, `--cover <image>`, `--submit` |

### Reading Commands

All reading commands support `--json` / `-j` for machine-readable JSON output.

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `read <tweet_url>` | Read a single tweet | `--json` |
| `timeline <user>` | Read user's timeline | `-n <count>` (default: 10, max: 200), `--json` |
| `search <query>` | Search tweets | `-n <count>`, `--latest`, `--json` |

### Utility Commands

| Command | Purpose |
|---------|---------|
| `check` | Verify environment (Chrome, permissions, dependencies) |

## Workflow Patterns

### Pattern 1: Post a Tweet

```bash
# Preview first (no --submit)
xpost post 'Your tweet text here' -i /path/to/image.jpg

# Then submit
xpost post 'Your tweet text here' -i /path/to/image.jpg --submit
```

### Pattern 2: Read and Analyze Tweets

```bash
# Read a specific tweet
xpost read 'https://x.com/user/status/123456' --json

# Get recent tweets from a user
xpost timeline '@username' -n 20 --json

# Search for a topic
xpost search 'keyword or phrase' -n 15 --latest --json
```

When reading tweets for analysis, always use `--json` flag to get structured data that can be parsed programmatically.

### Pattern 3: Reply to a Tweet

```bash
# Preview reply
xpost reply 'https://x.com/user/status/123456' 'Great point!'

# Submit reply
xpost reply 'https://x.com/user/status/123456' 'Great point!' --submit
```

### Pattern 4: Quote Tweet with Commentary

```bash
# First read the original tweet
xpost read 'https://x.com/user/status/123456'

# Then quote it
xpost quote 'https://x.com/user/status/123456' 'My commentary' --submit
```

### Pattern 5: Publish an Article from Markdown

```bash
xpost article /path/to/article.md --title 'Article Title' --cover /path/to/cover.jpg --submit
```

The Markdown file supports YAML frontmatter for `title`, `subtitle`, and `cover`.

### Pattern 6: Multi-Account Operations

Use `--profile` to switch between accounts:

```bash
xpost --profile ~/.x-poster/account-a post 'From account A' --submit
xpost --profile ~/.x-poster/account-b post 'From account B' --submit
```

## JSON Output Schema

Reading commands with `--json` return structured data. Each tweet object contains:

```json
{
  "text": "Tweet content",
  "displayName": "Author Name",
  "handle": "@handle",
  "timestamp": "2025-01-01T00:00:00.000Z",
  "timeText": "localized time",
  "images": ["https://..."],
  "videos": ["https://..."],
  "metrics": {"replies": "N", "retweets": "N", "likes": "N", "views": "N"},
  "quoted": null,
  "url": "https://x.com/user/status/ID"
}
```

- `read` returns a single object
- `timeline` and `search` return an array of objects

## Reference Documents

For detailed command options and arguments, consult `references/command_reference.md`.

For troubleshooting common issues (Chrome startup, login, paste failures, DOM selector updates), consult `references/troubleshooting.md`.

## Important Notes

1. **Preview before submit**: Always run without `--submit` first to verify content is correct.
2. **Rate limiting**: Avoid rapid-fire posting. X may flag or suspend accounts for automated behavior.
3. **DOM changes**: X updates its interface frequently. If selectors break, check `references/troubleshooting.md` for the current selector list and update the source code accordingly.
4. **macOS only**: This tool uses macOS-specific APIs (AppKit clipboard, osascript keystroke). It does not work on Linux or Windows.
5. **Chrome profile**: The tool creates a dedicated Chrome profile. Do not use it simultaneously with the user's regular Chrome browsing.
