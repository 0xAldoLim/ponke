"""Portable PostgreSQL backup; writes binary directly, avoiding shell encoding corruption."""

import argparse
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("destination", type=Path)
args = parser.parse_args()
args.destination.parent.mkdir(parents=True, exist_ok=True)
with args.destination.open("xb") as output:
    subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "pg_dump", "-U", "ponke", "-d", "ponke", "-Fc"],
        stdout=output,
        check=True,
    )
print(f"Backup saved to {args.destination}. Store it encrypted and off-host.")
