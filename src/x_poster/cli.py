"""
CLI main entry point for x-poster.

Registers all subcommands: post, video, quote, article, check.
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
    """xpost - Post to X (Twitter) via Chrome CDP protocol.

    Uses a real Chrome browser with CDP to create posts, upload media,
    quote tweets, and publish long-form articles on X.
    """
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
    ctx.obj["chrome_path"] = chrome_path


# Import and register subcommands
from .commands.post import post
from .commands.video import video
from .commands.quote import quote
from .commands.article import article
from .commands.check import check

cli.add_command(post)
cli.add_command(video)
cli.add_command(quote)
cli.add_command(article)
cli.add_command(check)


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
