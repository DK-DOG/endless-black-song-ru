"""Copy the local Russian-patch work into _ru_backup.

The backup stays on this computer. It includes both exe files, so it must
not be published. The shareable part is the rusifikator folder.
"""

import hashlib
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import CHUNK, EXE_NAME, ROOT, configure_stdio, die

GAME = ROOT.parent
BACKUP = GAME / "_ru_backup"


def copy_hashed(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with open(source, "rb") as src, open(target, "wb") as dst:
        for chunk in iter(lambda: src.read(CHUNK), b""):
            digest.update(chunk)
            dst.write(chunk)
    shutil.copystat(source, target)
    return digest.hexdigest(), target.stat().st_size


def copy_tree_skip_save(source, target):
    if not source.is_dir():
        die("Нет папки " + str(source))
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [name for name in dirnames if name.lower() != "save"]
        relative = Path(dirpath).relative_to(source)
        destination = target / relative
        destination.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            shutil.copy2(Path(dirpath) / name, destination / name)


def main():
    configure_stdio()
    patched = GAME / EXE_NAME
    original = GAME / (EXE_NAME + ".bak")
    if not patched.is_file() or not original.is_file():
        die("В папке игры нет exe или exe.bak.")
    BACKUP.mkdir(exist_ok=True)
    print("Копирую пропатченный exe...")
    patched_hash, patched_size = copy_hashed(patched, BACKUP / EXE_NAME)
    print("Копирую оригинал...")
    original_hash, original_size = copy_hashed(original, BACKUP / (EXE_NAME + ".bak"))
    note = GAME / "Как играть по-русски.txt"
    if note.is_file():
        shutil.copy2(note, BACKUP / note.name)
    print("Копирую файлы перевода и рабочие скрипты...")
    copy_tree_skip_save(GAME / "www", BACKUP / "www")
    copy_tree_skip_save(
        GAME / "%default folder%" / "www",
        BACKUP / "%default folder%" / "www",
    )
    work = GAME / "_ru_work"
    if work.is_dir():
        shutil.copytree(
            work,
            BACKUP / "_ru_work",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    lines = [
        "Локальный бэкап русского перевода Endless Black Song.",
        "",
        "Это копия для этого компьютера. Сюда входят оба exe игры.",
        "В git эту папку класть не нужно.",
        "Для публикации нужна только папка rusifikator.",
        "",
        "EndlessBlackSong.exe — игра с уже записанным переводом.",
        "SHA-256: " + patched_hash,
        "Размер: %d" % patched_size,
        "",
        "EndlessBlackSong.exe.bak — оригинал до перевода.",
        "SHA-256: " + original_hash,
        "Размер: %d" % original_size,
        "",
        "www и «%default folder%\\www» — текст, шрифт и русские картинки.",
        "Папка save сознательно не копировалась.",
        "_ru_work — скрипты, которыми перевод собирался.",
        "",
        "Чтобы вернуть игру из этого бэкапа, закройте её и скопируйте",
        "EndlessBlackSong.exe обратно в папку игры. Сохранения не трогать.",
        "",
    ]
    (BACKUP / "BACKUP.txt").write_text("\n".join(lines), encoding="utf-8")
    print("Бэкап записан:", BACKUP)
    print(patched_hash)
    print(original_hash)


if __name__ == "__main__":
    main()
