"""Restore into the configured Compose database. Stop the app first."""

import argparse
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("backup", type=Path)
parser.add_argument("--replace-database-contents", action="store_true")
args = parser.parse_args()
if not args.replace_database_contents:
    parser.error(
        "This replaces existing data. Stop the app, take a backup, then use --replace-database-contents."
    )
with args.backup.open("rb") as source:
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "pg_restore",
            "-U",
            "ponke",
            "-d",
            "ponke",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--exit-on-error",
        ],
        stdin=source,
        check=True,
    )
print("Restore complete. Verify the database before restarting the app.")
