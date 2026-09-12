#!/usr/bin/env python3
"""Compatibility entry point for existing desktop shortcuts."""
import os
import sys

# Support both a source checkout and the installed ~/.local/bin script.
for candidate in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  os.path.expanduser("~/.local/lib")):
    if os.path.isfile(os.path.join(candidate, "rogcontrol", "__init__.py")):
        sys.path.insert(0, candidate)
        break

from rogcontrol.cli import main

if __name__ == "__main__":
    sys.exit(main(['profile', 'next'] + sys.argv[1:]))
