"""
CLI main entry point for x-poster.

Registers all subcommands: post, video, quote, article, read, timeline, search, check.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

import click

from . import __version__


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.version_option(version=__version__, prog_name="xpost")
@click.option(
    "--profile",
    default=None,
    envvar="XPOST_PROFILE",
    help="Chrome profile directory (default: ~/.local/share/x-poster-profile)",
)
@click.option(
    "--chrome-path",
    default=None,
    envvar="CHROME_PATH",
    help="Path to Chrome executable",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, profile: Optional[str], chrome_path: Optional[str], verbose: bool) -> None:
    """xpost - Post to and read from X (Twitter) via Chrome CDP protocol.

    Uses a real Chrome browser with CDP to create posts, upload media,
    quote tweets, publish long-form articles, and read tweets on X.
    """
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    ctx.obj["chrome_path"] = chrome_path


# Import and register subcommands
from .commands.post import post
from .commands.video import video
from .commands.quote import quote
from .commands.reply import reply
from .commands.article import article
from .commands.read import read_tweet
from .commands.timeline import timeline
from .commands.search import search
from .commands.check import check

cli.add_command(post)
cli.add_command(video)
cli.add_command(quote)
cli.add_command(reply)
cli.add_command(article)
cli.add_command(read_tweet)
cli.add_command(timeline)
cli.add_command(search)
cli.add_command(check)


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
