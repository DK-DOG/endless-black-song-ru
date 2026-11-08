"""Build «Русификатор Endless Black Song.exe» from the installer source and payload.

Players do not run this. It is the build command for the exe that can be
published alongside the source.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    spec = ROOT / "installer.spec"
    if not spec.is_file():
        raise SystemExit("Нет installer.spec рядом с папкой src.")
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(ROOT),
            "--workpath",
            str(ROOT / "build"),
            str(spec),
        ],
        cwd=ROOT,
    )
    built = ROOT / "Русификатор Endless Black Song.exe"
    if not built.is_file():
        raise SystemExit("PyInstaller не создал exe.")
    print(built)
    print(built.stat().st_size)


if __name__ == "__main__":
    main()
