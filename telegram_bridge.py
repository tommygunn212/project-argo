"""Launcher for ARGO's Telegram bridge (core/telegram_bridge.py).

    .\\.venv\\Scripts\\python.exe telegram_bridge.py
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from core.telegram_bridge import run

    sys.exit(asyncio.run(run()))
