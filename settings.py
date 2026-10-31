"""Read private settings from the .env file, which git ignores.

A value already in the environment wins, so a test server can use its own.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"


def load_env_file(path=ENV_FILE):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.partition("=")
        if separator and not line.lstrip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip())
