#!/usr/bin/env python3
"""Aria formatter bootstrap launcher."""

from format_bootstrap import install_global_formatter
from main import main as bot_main


if __name__ == "__main__":
    install_global_formatter()
    bot_main()
