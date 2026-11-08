"""Rebuild payload/ from the original exe and the patched exe.

Run this from a game folder that contains both:

    EndlessBlackSong.exe       the patched game
    EndlessBlackSong.exe.bak   the original game

The rusifikator folder must sit inside that game folder.
Players do not run this. They run Установить.bat, which uses payload/.
"""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vfs
from common import CHUNK, EXE_NAME, PAYLOAD, ROOT, configure_stdio, die, sha256_bytes

GAP = 32


def game_dir():
    folder = ROOT.parent
    patched = folder / EXE_NAME
    original = folder / (EXE_NAME + ".bak")
    if not patched.is_file() or not original.is_file():
        die(
            "Нужны оба файла рядом с папкой rusifikator: "
            "EndlessBlackSong.exe и EndlessBlackSong.exe.bak."
        )
    return folder, original, patched


def differing_ranges(original, patched):
    ranges = []
    open_start = None
    offset = 0
    original_hash = hashlib.sha256()
    patched_hash = hashlib.sha256()
    with open(original, "rb") as left, open(patched, "rb") as right:
        while True:
            old = left.read(CHUNK)
            new = right.read(CHUNK)
            if len(old) != len(new):
                die("Оригинал и пропатченный exe разного размера.")
            if not old:
                break
            original_hash.update(old)
            patched_hash.update(new)
            for index, (before, after) in enumerate(zip(old, new)):
                if before != after:
                    if open_start is None:
                        open_start = offset + index
                elif open_start is not None:
                    ranges.append((open_start, offset + index))
                    open_start = None
            offset += len(old)
    if open_start is not None:
        ranges.append((open_start, offset))
    merged = []
    for start, end in ranges:
        if merged and start - merged[-1][1] <= GAP:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged, offset, original_hash.hexdigest(), patched_hash.hexdigest()


def file_spans(original):
    with open(original, "rb") as handle:
        info = vfs.parse_vfs(handle)
        tree = vfs.build_tree(info["nodes"])
        spans = []
        for path, node in vfs.iter_files(tree):
            start = node["offset"]
            spans.append((path.replace("\\", "/"), start, start + node["stored"]))
    return spans


def label_hunk(start, end, spans):
    names = [path for path, left, right in spans if start < right and end > left]
    return ", ".join(names) if names else "outside-packed-files"


def hash_applied(original, hunks):
    digest = hashlib.sha256()
    with open(original, "rb") as handle:
        position = 0
        for hunk in hunks:
            digest.update(handle.read(hunk["offset"] - position))
            skipped = handle.read(hunk["length"])
            if len(skipped) != hunk["length"]:
                die("Не удалось прочитать оригинальный кусок exe.")
            if sha256_bytes(skipped) != hunk["original_sha256"]:
                die("Сборка патча разошлась с оригиналом: " + hunk["path"])
            digest.update(hunk["data"])
            position = hunk["offset"] + hunk["length"]
        digest.update(handle.read())
    return digest.hexdigest()


def overlay_list(www):
    found = []
    for dirpath, dirnames, filenames in os.walk(www):
        dirnames[:] = [name for name in dirnames if name.lower() != "save"]
        for name in filenames:
            path = Path(dirpath) / name
            relative = path.relative_to(www).as_posix()
            parts = relative.split("/")
            if parts[0] == "rus_loc":
                found.append(relative)
            elif parts[0] == "img" and "RUS" in parts:
                found.append(relative)
            elif relative == "img/pictures/GalleryTutorial_ru.png":
                found.append(relative)
    return sorted(found)


def same_file(left, right):
    if not left.is_file() or not right.is_file():
        return False
    if left.stat().st_size != right.stat().st_size:
        return False
    with open(left, "rb") as a, open(right, "rb") as b:
        while True:
            ca = a.read(CHUNK)
            cb = b.read(CHUNK)
            if ca != cb:
                return False
            if not ca:
                return True


def collect_files(game):
    www = game / "www"
    other = game / "%default folder%" / "www"
    names = overlay_list(www)
    if "rus_loc/system.csv" not in names:
        die("В www нет rus_loc/system.csv.")
    if "img/pictures/GalleryTutorial_ru.png" not in names:
        die("В www нет русской подсказки галереи.")
    for relative in names:
        if not same_file(www / relative, other / relative):
            die("Файл перевода не совпадает во втором дереве www: " + relative)
    system = (www / "rus_loc" / "system.csv").read_text(encoding="utf-8-sig")
    if "Тилль" in system or "Тилл" not in system:
        die("system.csv не проходит проверку имени Тилл.")
    header = system.splitlines()[0]
    if header.split(";")[-1] != "RUS":
        die("В system.csv нет столбца RUS.")
    return names


def reset_dir(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def main():
    configure_stdio()
    game, original, patched = game_dir()
    print("Сравниваю exe...")
    ranges, size, original_hash, patched_hash = differing_ranges(original, patched)
    if not ranges:
        die("Exe ничем не отличается от оригинала. Патч собирать не из чего.")
    spans = file_spans(original)
    hunks = []
    with open(patched, "rb") as handle:
        for number, (start, end) in enumerate(ranges, start=1):
            handle.seek(start)
            data = handle.read(end - start)
            if len(data) != end - start:
                die("Короткое чтение пропатченного exe.")
            with open(original, "rb") as source:
                source.seek(start)
                old = source.read(len(data))
            hunks.append(
                {
                    "path": label_hunk(start, end, spans),
                    "offset": start,
                    "length": len(data),
                    "original_sha256": sha256_bytes(old),
                    "patched_sha256": sha256_bytes(data),
                    "file": "hunks/%04d.bin" % number,
                    "original_file": "hunks/%04d.orig.bin" % number,
                    "data": data,
                    "old": old,
                }
            )
    applied = hash_applied(original, hunks)
    if applied != patched_hash:
        die("Собранные куски не превращают оригинал в текущий exe.")

    names = collect_files(game)
    note_path = game / "Как играть по-русски.txt"
    if not note_path.is_file():
        die("Нет файла «Как играть по-русски.txt».")

    reset_dir(PAYLOAD / "hunks")
    reset_dir(PAYLOAD / "files")
    reset_dir(PAYLOAD / "root")
    file_records = []
    for relative in names:
        source = game / "www" / relative
        target = PAYLOAD / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        target.write_bytes(data)
        file_records.append(
            {"path": relative, "sha256": sha256_bytes(data), "size": len(data)}
        )
    note = note_path.read_bytes()
    (PAYLOAD / "root" / note_path.name).write_bytes(note)

    manifest = {
        "game": "Endless Black Song",
        "exe_name": EXE_NAME,
        "exe_size": size,
        "original_sha256": original_hash,
        "patched_sha256": patched_hash,
        "hunks": [
            {key: value for key, value in hunk.items() if key not in ("data", "old")}
            for hunk in hunks
        ],
        "files": file_records,
        "root_files": [
            {"name": note_path.name, "sha256": sha256_bytes(note), "size": len(note)}
        ],
        "fonts": ["georgia.ttf", "georgiab.ttf"],
    }
    (PAYLOAD / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for hunk in hunks:
        (PAYLOAD / hunk["file"]).write_bytes(hunk["data"])
        (PAYLOAD / hunk["original_file"]).write_bytes(hunk["old"])
    changed = sum(hunk["length"] for hunk in hunks)
    print(
        "Патч собран: %d кусков, %d байт внутри exe, %d файлов перевода."
        % (len(hunks), changed, len(file_records))
    )
    print("Оригинал ", original_hash)
    print("Перевод ", patched_hash)


if __name__ == "__main__":
    main()
