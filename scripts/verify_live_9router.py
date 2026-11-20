#!/usr/bin/env python3
"""Compatibility forwarder to hermes_teamwork.scripts.verify_live_9router"""
from pathlib import Path
import sys

_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from hermes_teamwork.scripts.verify_live_9router import main

if __name__ == "__main__":
    main()
