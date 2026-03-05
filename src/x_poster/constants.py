"""
Shared constants and selectors for x-poster.

Centralizes X DOM selectors and common configuration
to avoid duplication across command modules.
"""

# ── Tweet compose/edit selectors ──────────────────────────────────
TWEET_EDITOR = '[data-testid="tweetTextarea_0"]'
TWEET_BUTTON = '[data-testid="tweetButton"], [data-testid="tweetButtonInline"]'

# ── Tweet read selectors ──────────────────────────────────────────
TWEET_ARTICLE = 'article[data-testid="tweet"]'
TWEET_TEXT = '[data-testid="tweetText"]'
USER_NAME = '[data-testid="User-Name"]'

# ── Interaction selectors ─────────────────────────────────────────
REPLY_BUTTON = '[data-testid="reply"]'
RETWEET_BUTTON = '[data-testid="retweet"]'
UNRETWEET_BUTTON = '[data-testid="unretweet"]'

# ── Auth selectors ────────────────────────────────────────────────
LOGIN_INDICATOR = '[data-testid="loginButton"], [href="/login"]'
