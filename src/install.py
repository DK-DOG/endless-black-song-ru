"""Install the Russian translation onto an existing Endless Black Song copy.

The game exe must be the original build this patch was made from, or a copy
that this same patch has already modified. The installer checks both hashes.
It writes only the changed bytes inside the exe, then copies the translation
files. Save files are left alone except locale.rpgsave, which is set to RUS.

With no folder argument, a packaged installer looks for the Steam copy first.
If that copy is not there, it opens the usual folder picker and does not
explain the search. A write-open of the exe is not used as a "game is running"
check: Explorer and antivirus refuse that open while the folder is merely
being viewed, and the patch never writes the original file in place.
"""

import argparse
import errno
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import EXE_NAME, PAYLOAD, ROOT, configure_stdio, sha256_bytes, sha256_file

FONTS = Path(r"C:\Windows\Fonts")
WWW_ROOTS = ("www", str(Path("%default folder%") / "www"))
APP_ID = "3707780"
REMOVER_NAME = "Удалить русификатор.exe"
CREATE_NO_WINDOW = 0x08000000
progress = None
pending_deletes = []


class Progress:
    def __init__(self, enabled):
        self.enabled = enabled
        self.root = None
        if not enabled:
            return
        import tkinter as tk

        self.root = tk.Tk()
        self.root.title("Русский перевод")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.label = tk.Label(
            self.root,
            text="Подождите.",
            padx=28,
            pady=18,
            wraplength=440,
            justify="left",
        )
        self.label.pack()
        self.root.update()

    def set(self, text):
        print(text)
        if self.root is not None:
            self.label.config(text=text)
            self.root.update()

    def finish(self, text):
        print(text)
        if self.root is None:
            return
        from tkinter import messagebox

        messagebox.showinfo("Русский перевод", text, parent=self.root)
        self.root.destroy()
        self.root = None

    def error(self, text):
        print(text, file=sys.stderr)
        if self.root is None:
            return
        from tkinter import messagebox

        messagebox.showerror("Русский перевод", text, parent=self.root)
        self.root.destroy()
        self.root = None


def fail(message):
    if progress is not None and progress.enabled:
        progress.error(message)
    else:
        print(message, file=sys.stderr)
    raise SystemExit(1)


def norm_key(folder):
    return os.path.normcase(os.path.abspath(str(folder)))


def unescape_vdf(value):
    return value.replace("\\\\", "\\")


def drive_ready(folder):
    text = str(folder)
    if text.startswith("\\\\"):
        return True
    drive = os.path.splitdrive(text)[0]
    if not drive:
        return True
    return os.path.exists(drive + "\\")


def steam_client_dirs():
    found = []
    seen = set()

    def add(folder):
        if not folder:
            return
        path = Path(str(folder).replace("/", "\\"))
        key = norm_key(path)
        if key in seen or not drive_ready(path) or not path.is_dir():
            return
        seen.add(key)
        found.append(path)

    queries = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    )
    for hive, key, value in queries:
        try:
            with winreg.OpenKey(hive, key) as handle:
                raw, _kind = winreg.QueryValueEx(handle, value)
        except OSError:
            continue
        add(raw)
    program_files = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
    if program_files:
        add(Path(program_files) / "Steam")
    return found


def libraries_from_vdf(steam):
    vdf = Path(steam) / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file():
        return []
    try:
        text = vdf.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    found = []
    for match in re.finditer(r'"path"\s+"([^"]*)"', text):
        found.append(Path(unescape_vdf(match.group(1))))
    for match in re.finditer(r'"\d+"\s+"([^"]*)"', text):
        value = unescape_vdf(match.group(1))
        if ":\\" in value or ":/" in value or value.startswith("\\\\"):
            found.append(Path(value))
    return found


def steam_libraries():
    libraries = []
    seen = set()

    def add(folder):
        if folder is None:
            return
        path = Path(folder)
        key = norm_key(path)
        if key in seen:
            return
        seen.add(key)
        libraries.append(path)

    for steam in steam_client_dirs():
        add(steam)
        for extra in libraries_from_vdf(steam):
            add(extra)
    return libraries


def install_dir_name(library):
    manifest = Path(library) / "steamapps" / ("appmanifest_%s.acf" % APP_ID)
    if not manifest.is_file():
        return None
    try:
        text = manifest.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    match = re.search(r'"installdir"\s+"([^"]*)"', text)
    if not match:
        return None
    name = unescape_vdf(match.group(1))
    return name or None


def game_dirs_from_libraries(libraries):
    found = []
    seen = set()
    for library in libraries:
        if not drive_ready(library):
            continue
        name = install_dir_name(library)
        if not name:
            continue
        folder = Path(library) / "steamapps" / "common" / name
        if not (folder / EXE_NAME).is_file():
            continue
        key = norm_key(folder)
        if key in seen:
            continue
        seen.add(key)
        found.append(folder)
    return found


def find_steam_game():
    try:
        found = game_dirs_from_libraries(steam_libraries())
    except Exception:
        return None
    if len(found) == 1:
        return found[0]
    return None


def ask_game_folder():
    from tkinter import filedialog

    progress.set("Выберите папку, в которой лежит EndlessBlackSong.exe.")
    parent = progress.root
    extra = None
    if parent is None:
        import tkinter as tk

        extra = tk.Tk()
        extra.withdraw()
        parent = extra
    chosen = filedialog.askdirectory(
        title="Папка с Endless Black Song",
        parent=parent,
    )
    if extra is not None:
        extra.destroy()
    if not chosen:
        fail("Папка не выбрана. Ничего не изменено.")
    return Path(chosen)


def game_folder(argument):
    if argument:
        folder = Path(argument).resolve()
    elif not getattr(sys, "frozen", False) and (ROOT.parent / EXE_NAME).is_file():
        folder = ROOT.parent
    else:
        folder = find_steam_game()
        if folder is None:
            folder = ask_game_folder()
    exe = folder / EXE_NAME
    if not exe.is_file():
        fail(
            "В этой папке нет EndlessBlackSong.exe.\n"
            "Выберите папку игры, где лежит этот файл. Ничего не изменено."
        )
    return folder, exe


def load_manifest():
    path = PAYLOAD / "manifest.json"
    if not path.is_file():
        fail("Нет payload/manifest.json. Папка установщика собрана не полностью.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    last = 0
    for hunk in manifest["hunks"]:
        if hunk["offset"] < last:
            fail("Патч повреждён: куски exe идут не по порядку.")
        blob = (PAYLOAD / hunk["file"]).read_bytes()
        if len(blob) != hunk["length"]:
            fail("Патч повреждён: " + hunk["file"])
        if sha256_bytes(blob) != hunk["patched_sha256"]:
            fail("Патч повреждён: не сходится контрольная сумма " + hunk["file"])
        if "original_file" not in hunk:
            fail("Патч собран без данных для удаления перевода.")
        original = (PAYLOAD / hunk["original_file"]).read_bytes()
        if len(original) != hunk["length"] or sha256_bytes(original) != hunk["original_sha256"]:
            fail("Патч повреждён: не сходится контрольная сумма " + hunk["original_file"])
        last = hunk["offset"] + hunk["length"]
    for record in manifest["files"]:
        blob = (PAYLOAD / "files" / record["path"]).read_bytes()
        if sha256_bytes(blob) != record["sha256"]:
            fail("Повреждён файл перевода: " + record["path"])
    for record in manifest["root_files"]:
        blob = (PAYLOAD / "root" / record["name"]).read_bytes()
        if sha256_bytes(blob) != record["sha256"]:
            fail("Повреждён файл: " + record["name"])
    return manifest


def hidden_run(args):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=25,
        creationflags=CREATE_NO_WINDOW,
    )


def game_is_running():
    try:
        completed = hidden_run(
            ["tasklist", "/FI", "IMAGENAME eq EndlessBlackSong.exe", "/NH"]
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "endlessblacksong.exe" in completed.stdout.lower()


def launcher_holds_game():
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.ProcessId -ne $PID -and "
        "$_.Name -ne 'powershell.exe' -and $_.Name -ne 'pwsh.exe' -and "
        "$_.CommandLine -like '*EndlessBlackSong.exe*' } | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    try:
        completed = hidden_run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ]
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(completed.stdout.strip())


def held_by_game():
    if game_is_running():
        return True
    return launcher_holds_game()


def fail_busy(unchanged, game):
    tail = "Ничего не изменено." if unchanged else "Оригинал не тронут."
    if game:
        fail("Файл игры занят. Закройте игру и запустите установщик снова. " + tail)
    fail(
        "Не получилось записать файл игры: его держит другая программа, не сама игра. "
        "Закройте окно папки с игрой в проводнике и запустите установщик снова. "
        + tail
    )


def run_while_busy(action, unchanged):
    for attempt in range(30):
        try:
            action()
            return
        except PermissionError:
            if attempt == 0 and held_by_game():
                fail_busy(unchanged, True)
            if attempt == 0:
                progress.set(
                    "Файл игры на секунду занят другой программой. Жду и пробую снова."
                )
            time.sleep(0.5)
    fail_busy(unchanged, held_by_game())


def clear_readonly(path):
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & stat.S_IWRITE:
        return
    try:
        path.chmod(mode | stat.S_IWRITE)
    except OSError:
        pass


def _mark_delete_on_close(path):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(
        str(path),
        0x00010000,
        0x1 | 0x2 | 0x4,
        None,
        3,
        0x04000000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if not handle or handle == invalid:
        return False
    kernel32.CloseHandle(handle)
    return True


def _hide(path):
    import ctypes

    ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)


def schedule_delete(path):
    if path is None or not path.exists():
        return
    clear_readonly(path)
    try:
        path.unlink()
        return
    except OSError:
        pass
    hidden = path.with_name("~$%s.tmp" % uuid.uuid4().hex)
    try:
        path.replace(hidden)
        path = hidden
        _hide(path)
    except OSError:
        pass
    if path.parent != Path(tempfile.gettempdir()):
        junk = Path(tempfile.gettempdir()) / path.name
        try:
            path.replace(junk)
            path = junk
        except OSError:
            pass
    if _mark_delete_on_close(path):
        return
    try:
        if path.exists():
            path.unlink()
            return
    except OSError:
        pass
    if path.exists():
        pending_deletes.append(path)


def flush_pending_deletes():
    current = list(pending_deletes)
    pending_deletes.clear()
    for path in current:
        schedule_delete(path)


def leftovers_in(folder):
    folder_key = norm_key(folder).rstrip("\\") + "\\"
    found = []
    for path in pending_deletes:
        if path.exists() and norm_key(path).startswith(folder_key):
            found.append(path.name)
    return found


def _restore_original(exe, aside):
    if exe.exists() or not aside.exists():
        return
    try:
        aside.rename(exe)
    except OSError:
        pass


def _place_once(temporary, exe, aside):
    clear_readonly(exe)
    if exe.exists() and aside.exists():
        schedule_delete(aside)
    if exe.exists() and aside.exists():
        raise PermissionError(aside)
    try:
        temporary.replace(exe)
    except PermissionError:
        clear_readonly(exe)
        exe.rename(aside)
        try:
            temporary.rename(exe)
        except Exception:
            if not exe.exists() and aside.exists():
                aside.rename(exe)
            raise
    if aside.exists() and exe.exists() and not temporary.exists():
        schedule_delete(aside)


def place_new_exe(temporary, exe):
    aside = exe.with_name(exe.name + ".install-old")
    warned = False
    for _attempt in range(30):
        try:
            _place_once(temporary, exe, aside)
        except PermissionError:
            _restore_original(exe, aside)
            if not warned:
                warned = True
                if held_by_game():
                    fail_busy(False, True)
                progress.set(
                    "Файл игры на секунду занят другой программой. Жду и пробую снова."
                )
            time.sleep(0.5)
            continue
        except OSError:
            _restore_original(exe, aside)
            raise
        if exe.exists() and not temporary.exists():
            return
    _restore_original(exe, aside)
    fail_busy(False, held_by_game())


def copy_overlay(game, manifest):
    for record in manifest["files"]:
        source = PAYLOAD / "files" / record["path"]
        for root_name in WWW_ROOTS:
            target = game / root_name / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if sha256_file(target) != record["sha256"]:
                fail("Не удалось записать " + str(target))
    for record in manifest["root_files"]:
        source = PAYLOAD / "root" / record["name"]
        target = game / record["name"]
        shutil.copyfile(source, target)


def copy_fonts(game, manifest):
    sources = []
    for name in manifest["fonts"]:
        source = FONTS / name
        if not source.is_file():
            fail(
                "В Windows нет шрифта %s. Он нужен для русских букв. "
                "Exe не менялся, если это сообщение появилось до записи." % name
            )
        sources.append(source)
    for source in sources:
        for root_name in WWW_ROOTS:
            target_dir = game / root_name / "fonts"
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target_dir / source.name)


def write_locale(game):
    for root_name in WWW_ROOTS:
        save_dir = game / root_name / "save"
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / "locale.rpgsave").write_bytes(b"RUS")


def discard_temp(temporary, exe):
    if not temporary.exists():
        return
    try:
        if temporary.samefile(exe):
            return
    except OSError:
        pass
    try:
        temporary.unlink()
    except OSError:
        pass


def rewrite_exe(exe, manifest, restore):
    blob_key = "original_file" if restore else "file"
    before_key = "patched_sha256" if restore else "original_sha256"
    after_hash = manifest["original_sha256"] if restore else manifest["patched_sha256"]
    mismatch = (
        "Кусок exe не совпал с переводом ("
        if restore
        else "Кусок exe не совпал с оригиналом ("
    )
    blobs = []
    with open(exe, "rb") as handle:
        for hunk in manifest["hunks"]:
            handle.seek(hunk["offset"])
            current = handle.read(hunk["length"])
            if len(current) != hunk["length"] or sha256_bytes(current) != hunk[before_key]:
                fail(mismatch + hunk["path"] + "). Ничего не изменено.")
            blobs.append((hunk, (PAYLOAD / hunk[blob_key]).read_bytes()))
    temporary = exe.with_name(exe.name + ".install-tmp")
    progress.set("Копирую exe перед записью.")

    def copy_temp():
        shutil.copyfile(exe, temporary)

    try:
        run_while_busy(copy_temp, True)
        with open(temporary, "r+b") as handle:
            for hunk, blob in blobs:
                handle.seek(hunk["offset"])
                handle.write(blob)
        if sha256_file(temporary) != after_hash:
            fail("После записи контрольная сумма exe не сошлась. Исходный файл на месте.")
        place_new_exe(temporary, exe)
    except OSError as exc:
        discard_temp(temporary, exe)
        if exc.errno == errno.ENOSPC:
            fail(
                "Не хватило свободного места для временной копии файла игры. "
                "Ничего не изменено."
            )
        raise
    except BaseException:
        discard_temp(temporary, exe)
        raise


def original_locale_bytes(manifest):
    for hunk in manifest["hunks"]:
        if hunk["path"].endswith("locale.rpgsave"):
            return (PAYLOAD / hunk["original_file"]).read_bytes()
    fail("В патче нет исходного файла языка.")


def prune_empty_parents(directory, stop):
    stop_key = norm_key(stop)
    current = directory
    while current.exists() and norm_key(current) != stop_key:
        try:
            if any(current.iterdir()):
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


def delete_added_files(game, manifest):
    targets = []
    for record in manifest["files"]:
        for root_name in WWW_ROOTS:
            targets.append(game / root_name / record["path"])
    for name in manifest["fonts"]:
        for root_name in WWW_ROOTS:
            targets.append(game / root_name / "fonts" / name)
    for record in manifest["root_files"]:
        targets.append(game / record["name"])
    stuck = []
    for path in targets:
        if not path.is_file():
            continue
        try:
            path.unlink()
        except OSError:
            stuck.append(str(path))
        else:
            prune_empty_parents(path.parent, game)
    return stuck


def write_locale_value(game, data):
    for root_name in WWW_ROOTS:
        save_dir = game / root_name / "save"
        if save_dir.is_dir():
            (save_dir / "locale.rpgsave").write_bytes(data)


def running_remover():
    return getattr(sys, "frozen", False) and Path(sys.executable).name == REMOVER_NAME


def place_remover(game):
    source = Path(sys.executable) if getattr(sys, "frozen", False) else ROOT / "Русификатор Endless Black Song.exe"
    if not source.is_file():
        fail(
            "Перевод записан, но нет файла установщика, чтобы положить «"
            + REMOVER_NAME
            + "». Запустите установщик снова, когда этот файл будет рядом."
        )
    target = game / REMOVER_NAME
    try:
        if source.resolve() == target.resolve():
            return
    except OSError:
        pass
    progress.set("Кладу в папку игры «" + REMOVER_NAME + "».")
    for attempt in range(30):
        try:
            shutil.copyfile(source, target)
            return
        except PermissionError:
            if attempt == 0 and held_by_game():
                fail(
                    "Перевод уже записан, но «"
                    + REMOVER_NAME
                    + "» не удалось положить: игра запущена. "
                    "Закройте её и запустите установщик снова."
                )
            if attempt == 0:
                progress.set("Файл удаления на секунду занят. Жду и пробую снова.")
            time.sleep(0.5)
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                fail(
                    "Перевод уже записан, но не хватило места для «"
                    + REMOVER_NAME
                    + "». Освободите место и запустите установщик снова."
                )
            raise
    fail(
        "Перевод уже записан, но не удалось положить «"
        + REMOVER_NAME
        + "». Закройте папку игры и запустите установщик снова."
    )


def removal_folder(argument):
    if argument:
        folder = Path(argument).resolve()
    elif running_remover():
        folder = Path(sys.executable).resolve().parent
    else:
        fail("Не указана папка игры. Ничего не изменено.")
    exe = folder / EXE_NAME
    if not exe.is_file():
        fail("В этой папке нет EndlessBlackSong.exe. Ничего не изменено.")
    return folder, exe


def spawn_delete_helper(path):
    env = os.environ.copy()
    env["EBS_REMOVER"] = str(path)
    script = (
        "$path = $env:EBS_REMOVER; "
        "for ($i = 0; $i -lt 600; $i++) { "
        "if (-not (Test-Path -LiteralPath $path)) { exit 0 }; "
        "try { Remove-Item -LiteralPath $path -Force -ErrorAction Stop; exit 0 } "
        "catch { Start-Sleep -Milliseconds 500 } }"
    )
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ],
        env=env,
        creationflags=CREATE_NO_WINDOW | 0x00000200,
    )


def delete_self_later():
    if not running_remover():
        return
    path = Path(sys.executable).resolve()
    hidden = path.with_name("~$%s.tmp" % uuid.uuid4().hex)
    try:
        path.rename(hidden)
        _hide(hidden)
        path = hidden
    except OSError:
        pass
    spawn_delete_helper(path)


def confirm_install(game, assume_yes):
    if not progress.enabled or assume_yes:
        return True
    from tkinter import messagebox

    progress.set("Установить русский перевод?")
    agreed = messagebox.askyesno(
        "Русский перевод",
        "Установить русский перевод в эту папку?\n\n"
        + str(game)
        + "\n\nСохранения не изменятся.",
        parent=progress.root,
    )
    if agreed:
        return True
    if progress.root is not None:
        progress.root.destroy()
        progress.root = None
    print("Установка отменена. Ничего не изменено.")
    return False


def uninstall(argument, manifest, assume_yes):
    if progress.enabled and not assume_yes:
        from tkinter import messagebox

        progress.set("Удалить русский перевод?")
        agreed = messagebox.askyesno(
            "Русский перевод",
            "Удалить русский перевод и вернуть игру к оригиналу?\n\n"
            "Сохранения не изменятся.",
            parent=progress.root,
        )
        if not agreed:
            if progress.root is not None:
                progress.root.destroy()
                progress.root = None
            print("Удаление отменено. Ничего не изменено.")
            return
    game, exe = removal_folder(argument)
    progress.set("Игра: " + str(game))
    if exe.stat().st_size != manifest["exe_size"]:
        fail(
            "Этот exe другого размера. Удаление остановлено. Ничего не изменено."
        )
    progress.set("Проверяю файл игры. Это займёт немного времени.")
    current = sha256_file(exe)
    if current == manifest["patched_sha256"]:
        progress.set("Возвращаю оригинальный файл игры.")
        rewrite_exe(exe, manifest, True)
        if sha256_file(exe) != manifest["original_sha256"]:
            fail("Exe после возврата не совпал с оригиналом. Файлы перевода не удалялись.")
    elif current == manifest["original_sha256"]:
        progress.set("Файл игры уже оригинальный. Убираю файлы перевода.")
    else:
        fail(
            "Этот exe не совпадает ни с оригиналом, ни с поставленным переводом. "
            "Ничего не изменено."
        )
    stuck = delete_added_files(game, manifest)
    write_locale_value(game, original_locale_bytes(manifest))
    self_delete = False
    remover = game / REMOVER_NAME
    if remover.is_file():
        own = False
        if getattr(sys, "frozen", False):
            try:
                own = remover.resolve() == Path(sys.executable).resolve()
            except OSError:
                own = False
        if own:
            self_delete = True
        else:
            try:
                remover.unlink()
            except OSError:
                stuck.append(str(remover))
    flush_pending_deletes()
    if self_delete:
        delete_self_later()
    extra = ""
    if stuck:
        extra = "\n\nНе удалось удалить: " + "; ".join(stuck)
    gone = self_delete and not remover.exists()
    if gone:
        closing = "Файл удаления убран из папки."
    elif self_delete:
        closing = "Этот файл сейчас удалится сам."
    else:
        closing = ""
    progress.finish(
        "Русский перевод удалён. Игра снова оригинальная.\n\n"
        "Сохранения не менялись."
        + ((" " + closing) if closing else "")
        + extra
    )


def main():
    global progress
    configure_stdio()
    parser = argparse.ArgumentParser(description="Установить русский перевод Endless Black Song")
    parser.add_argument("--remove", action="store_true", help="Удалить перевод из папки игры.")
    parser.add_argument("--yes", action="store_true", help="Не спрашивать подтверждение.")
    parser.add_argument(
        "game",
        nargs="?",
        help="Папка игры. Без аргумента exe ищет установку Steam, иначе спрашивает папку.",
    )
    args = parser.parse_args()
    progress = Progress(getattr(sys, "frozen", False) and not args.game)
    manifest = load_manifest()
    if args.remove or running_remover():
        uninstall(args.game, manifest, args.yes)
        return
    game, exe = game_folder(args.game)
    if not confirm_install(game, args.yes):
        return
    progress.set("Игра: " + str(game))
    if exe.stat().st_size != manifest["exe_size"]:
        fail(
            "Этот exe другого размера (%d байт). Перевод собран для файла в %d байт. "
            "Ничего не изменено." % (exe.stat().st_size, manifest["exe_size"])
        )
    for name in manifest["fonts"]:
        if not (FONTS / name).is_file():
            fail("В Windows нет шрифта " + name + ". Ничего не изменено.")
    progress.set("Проверяю файл игры. Это займёт немного времени.")
    current = sha256_file(exe)
    if current == manifest["patched_sha256"]:
        progress.set("Exe уже с этим переводом. Обновляю файлы перевода.")
    elif current == manifest["original_sha256"]:
        progress.set("Exe совпал с оригиналом. Записываю перевод.")
        rewrite_exe(exe, manifest, False)
        if sha256_file(exe) != manifest["patched_sha256"]:
            fail("Exe после замены не совпал с переводом.")
    else:
        fail(
            "Этот exe не совпадает ни с оригиналом, ни с уже поставленным переводом. "
            "Ничего не изменено. Нужна та же сборка игры, для которой собран патч."
        )
    copy_fonts(game, manifest)
    copy_overlay(game, manifest)
    write_locale(game)
    place_remover(game)
    flush_pending_deletes()
    note = ""
    names = leftovers_in(game)
    if names:
        note = (
            "\n\nНе удалось убрать временный файл %s. "
            "Удалите его после закрытия папки игры." % ", ".join(names)
        )
    progress.finish(
        "Готово.\n\n"
        "Запустите игру как обычно, через Steam или EndlessBlackSong.exe. "
        "Язык уже русский.\n\n"
        "Чтобы убрать перевод, закройте игру и откройте «"
        + REMOVER_NAME
        + "» в папке с игрой."
        + note
    )


if __name__ == "__main__":
    main()
