#!/usr/bin/env python3
"""Prepare the explicitly authorized personal-build credential resource. Never print the key."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "ios/PrivateResources/ReverseCADJevConfig.plist"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    key = args.key_file.read_text().strip()
    if not key or len(key) > 8192 or "\r" in key or "\n" in key:
        raise SystemExit("The configured key file does not contain a single API key.")
    result = subprocess.run(["git", "check-ignore", "-q", str(DESTINATION)], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit("Refusing to write a credential resource that is not ignored by Git.")
    DESTINATION.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(DESTINATION, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as stream:
        plistlib.dump({"apiKey": key}, stream, fmt=plistlib.FMT_BINARY)
    DESTINATION.chmod(0o600)
    print("Personal ReverseCAD direct-Jev resource prepared; key content is not logged.")


if __name__ == "__main__":
    main()
