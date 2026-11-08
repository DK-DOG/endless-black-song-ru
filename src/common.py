"""Shared helpers for the Endless Black Song Russian patch."""

import hashlib
import sys
from pathlib import Path

def bundle_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


ROOT = bundle_root()
PAYLOAD = ROOT / "payload"
EXE_NAME = "EndlessBlackSong.exe"
CHUNK = 1024 * 1024


def configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def die(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
