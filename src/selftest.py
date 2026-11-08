"""Apply the installer to a copy of the original exe and check the result.

This does not modify the installed game. It needs EndlessBlackSong.exe.bak
next to the rusifikator folder and about 2 GB of free space.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import EXE_NAME, ROOT, configure_stdio, die, sha256_file
from install import load_manifest


def snapshot_saves(game):
    save_dir = game / "%default folder%" / "www" / "save"
    if not save_dir.is_dir():
        return None
    return {
        path.name: (path.stat().st_mtime_ns, path.stat().st_size)
        for path in save_dir.iterdir()
        if path.is_file()
    }


def run_install(game):
    script = Path(__file__).resolve().parent / "install.py"
    return subprocess.run(
        [sys.executable, str(script), str(game)],
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_remove(game):
    script = Path(__file__).resolve().parent / "install.py"
    return subprocess.run(
        [sys.executable, str(script), "--remove", "--yes", str(game)],
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main():
    configure_stdio()
    game = ROOT.parent
    original = game / (EXE_NAME + ".bak")
    live = game / EXE_NAME
    if not original.is_file() or not live.is_file():
        die("Для проверки нужны exe и exe.bak в папке игры.")
    manifest = load_manifest()
    print("Считаю сумму установленной игры...")
    live_hash = sha256_file(live)
    if live_hash != manifest["patched_sha256"]:
        die("Установленная игра не совпадает с собранным патчем.")
    if sha256_file(original) != manifest["original_sha256"]:
        die("EndlessBlackSong.exe.bak не совпадает с оригиналом из патча.")
    saves = snapshot_saves(game)
    temp = Path(tempfile.mkdtemp(prefix="ebs-ru-test-"))
    bad = Path(tempfile.mkdtemp(prefix="ebs-ru-bad-"))
    try:
        print("Копирую оригинал во временную папку...")
        shutil.copyfile(original, temp / EXE_NAME)
        save_dir = temp / "%default folder%" / "www" / "save"
        other_save = temp / "www" / "save"
        save_dir.mkdir(parents=True)
        other_save.mkdir(parents=True)
        (save_dir / "file6.rpgsave").write_bytes(b"SAVE-MARKER")
        (save_dir / "global.rpgsave").write_bytes(b"GLOBAL-MARKER")
        (other_save / "file6.rpgsave").write_bytes(b"SAVE-MARKER-2")
        (save_dir / "locale.rpgsave").write_bytes(b"EN")

        first = run_install(temp)
        if first.returncode != 0:
            die("Первая установка во временную папку не удалась.")
        patched = temp / EXE_NAME
        if sha256_file(patched) != live_hash:
            die("Временный exe не совпал с установленной игрой.")
        if (save_dir / "file6.rpgsave").read_bytes() != b"SAVE-MARKER":
            die("Установщик изменил file6.rpgsave.")
        if (save_dir / "global.rpgsave").read_bytes() != b"GLOBAL-MARKER":
            die("Установщик изменил global.rpgsave.")
        if (other_save / "file6.rpgsave").read_bytes() != b"SAVE-MARKER-2":
            die("Установщик изменил сохранение в www/save.")
        if (save_dir / "locale.rpgsave").read_bytes() != b"RUS":
            die("Язык во временной папке не переключился на RUS.")
        if (other_save / "locale.rpgsave").read_bytes() != b"RUS":
            die("Язык во втором дереве не переключился на RUS.")
        sample = manifest["files"][0]["path"]
        left = (temp / "www" / sample).read_bytes()
        right = (temp / "%default folder%" / "www" / sample).read_bytes()
        if left != right or not left:
            die("Файл перевода не попал в оба дерева www.")
        for font_name in manifest["fonts"]:
            if not (temp / "www" / "fonts" / font_name).is_file():
                die("Шрифт не скопирован: " + font_name)
        if (temp / (EXE_NAME + ".bak")).exists():
            die("Установщик создал копию exe.bak.")
        remover = temp / "Удалить русификатор.exe"
        if not remover.is_file():
            die("В папке игры не появился файл удаления перевода.")

        second = run_install(temp)
        if second.returncode != 0:
            die("Повторная установка не удалась.")
        if sha256_file(patched) != manifest["patched_sha256"]:
            die("Повторная установка изменила exe.")
        if (save_dir / "file6.rpgsave").read_bytes() != b"SAVE-MARKER":
            die("Повторная установка изменила сохранение.")

        locale_hunk = next(
            hunk for hunk in manifest["hunks"] if hunk["path"].endswith("locale.rpgsave")
        )
        original_locale = (ROOT / "payload" / locale_hunk["original_file"]).read_bytes()
        removed = run_remove(temp)
        if removed.returncode != 0:
            die("Удаление перевода из временной папки не удалось.")
        if sha256_file(patched) != manifest["original_sha256"]:
            die("После удаления exe не вернулся к оригиналу.")
        if (save_dir / "file6.rpgsave").read_bytes() != b"SAVE-MARKER":
            die("Удаление изменило file6.rpgsave.")
        if (save_dir / "global.rpgsave").read_bytes() != b"GLOBAL-MARKER":
            die("Удаление изменило global.rpgsave.")
        if (other_save / "file6.rpgsave").read_bytes() != b"SAVE-MARKER-2":
            die("Удаление изменило сохранение в www/save.")
        if (save_dir / "locale.rpgsave").read_bytes() != original_locale:
            die("После удаления язык не вернулся к исходному.")
        if (other_save / "locale.rpgsave").read_bytes() != original_locale:
            die("После удаления язык во втором дереве не вернулся к исходному.")
        if (temp / "www" / sample).exists() or (temp / "%default folder%" / "www" / sample).exists():
            die("Файл перевода остался после удаления.")
        for font_name in manifest["fonts"]:
            if (temp / "www" / "fonts" / font_name).exists():
                die("Шрифт перевода остался: " + font_name)
        if (temp / "Как играть по-русски.txt").exists() or remover.exists():
            die("После удаления осталась записка или файл удаления.")
        if (temp / (EXE_NAME + ".bak")).exists():
            die("Удаление создало exe.bak.")

        (bad / EXE_NAME).write_bytes(b"not a game")
        rejected = run_install(bad)
        if rejected.returncode == 0:
            die("Чужой exe был принят.")
        if (bad / "www").exists():
            die("При отказе установщик всё равно создал файлы.")

        if sha256_file(live) != live_hash:
            die("Проверка изменила установленную игру.")
        if snapshot_saves(game) != saves:
            die("Проверка изменила сохранения установленной игры.")
    except Exception:
        print("Временные папки оставлены:")
        print(temp)
        print(bad)
        raise
    shutil.rmtree(temp)
    shutil.rmtree(bad)
    print("Проверка прошла: патч совпал с установленной игрой, сохранения не тронуты.")


if __name__ == "__main__":
    main()
