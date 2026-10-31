"""Copy the Telegram token from .env into n8n, which stores it encrypted.

Run with:  python automation/import_telegram_credential.py

n8n can only import from a file, so the token is in a temporary file for a moment.
That file is deleted even if the import fails. The ID below matches the one named in
the workflows, so nothing needs selecting in the editor. Running this again replaces
the old token.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import settings  # noqa: E402

LAUNCHER = Path(__file__).parent / "start_n8n.bat"


def credential(token):
    return [
        {
            "id": "marketpulseTelegram",
            "name": "MarketPulse Telegram",
            "type": "telegramApi",
            "data": {
                "accessToken": token,
                "baseUrl": os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org"),
            },
        }
    ]


def main():
    settings.load_env_file()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set in .env")
        return 1

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "credential.json"
        path.write_text(json.dumps(credential(token)), encoding="utf-8")
        result = subprocess.run(
            ["cmd", "/c", str(LAUNCHER), "import:credentials", f"--input={path}"],
            capture_output=True,
            text=True,
        )

    # The output is not printed: a failing import could repeat the file's contents.
    print("Token imported into n8n" if result.returncode == 0 else "Import failed")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
