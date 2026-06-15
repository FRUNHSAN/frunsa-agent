#!/usr/bin/env python3
"""Contract-Bound Agent — entry point.

Usage:
    python main.py frunhsan           # Cloud mode (DeepSeek)
    python main.py frunhsan --local   # Dual-backend with router
"""

import sys, os
from pathlib import Path

# Force UTF-8 on Windows — Rich emoji tables break under GBK
if os.name == "nt":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv; load_dotenv()

from core.config import Config
from core.container import Container
from core.repl import Repl


def main() -> None:
    cfg = Config.from_args(sys.argv)
    ctr = Container(cfg)
    repl = Repl(ctr)
    repl.run()


if __name__ == "__main__":
    main()
