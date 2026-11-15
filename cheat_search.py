"""
Cheat Search — проверка компьютера на читы для Minecraft.

Что проверяется:
  1. Запущенные программы: имя, заголовок окна, командная строка (так видно чит-клиент внутри javaw.exe).
  2. Файлы и папки: Рабочий стол, Загрузки, Документы, AppData, .minecraft (моды и версии), Temp.
  3. «Недавние файлы» Windows: видно, что открывали, даже если файл уже удалён.
  4. История запусков Windows (Prefetch): видно, какие программы запускали. Нужны права администратора.
  5. Исключения Защитника Windows. Нужны права администратора.

Сама по себе программа ничего не удаляет. Только если на экране результатов
нажать [4]: тогда найденные читы-файлы уходят в Корзину, а запущенные читы закрываются.
Список читов лежит в cheats.json, его можно дополнять.

Запуск:            python cheat_search.py
Проверка без меню: python cheat_search.py --scan
"""

import base64
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

try:
    import msvcrt   # чтение нажатых клавиш (есть только в Windows)
except ImportError:
    msvcrt = None


# ------------------------------------------------------------------ цвета

GREEN = "\033[92m"
CYAN = "\033[96m"
RED = "\033[91m"
YELLOW = "\033[93m"
GRAY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def enable_colors():
    """Включает поддержку цветов в консоли Windows."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        os.system("")


def strip_colors(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)


# ------------------------------------------------------------------ логотип

GLYPHS = {
    "C": [" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"],
    "H": ["██╗  ██╗", "██║  ██║", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "R": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"],
}

WIDTH = 64


def big_text(word):
    rows = []
    for row in range(6):
        rows.append("".join(GLYPHS[letter][row] for letter in word))
    return rows


def logo():
    lines = [""]
    for word in ("CHEAT", "SEARCH"):
        for row in big_text(word):
            lines.append(GREEN + BOLD + row.center(WIDTH).rstrip() + RESET)
        lines.append("")
    lines.append(GRAY + "проверка на читы Minecraft  •  v1.0".center(WIDTH).rstrip() + RESET)
    return "\n".join(lines)


def line():
    return GRAY + "  " + "─" * (WIDTH - 4) + RESET


def clear():
    os.system("cls" if os.name == "nt" else "clear")


# ------------------------------------------------------------------ клавиши и система

def read_key(allowed):
    """Ждёт нажатия одной из разрешённых клавиш и возвращает её."""
    if msvcrt is None:
        while True:
            answer = input("> ").strip()
            if answer in allowed:
                return answer
    while msvcrt.kbhit():
        msvcrt.getwch()
    while True:
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue
        if key in allowed:
            return key


def base_dir():
    # В .exe (PyInstaller) __file__ указывает во временную папку,
    # а cheats.json лежит рядом с самим .exe
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    if getattr(sys, "frozen", False):
        args = ""  # .exe перезапускает сам себя
    else:
        args = f'"{os.path.abspath(__file__)}"'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
    return result > 32


def run_powershell(script):
    """Запускает PowerShell-скрипт и возвращает результат как список словарей."""
    prefix = "$ErrorActionPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    encoded = base64.b64encode((prefix + script).encode("utf-16-le")).decode()
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            capture_output=True, timeout=120, creationflags=0x08000000,
        )
        data = json.loads(result.stdout.decode("utf-8-sig", errors="replace").strip() or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        return [data]
    return [item for item in data if isinstance(item, dict)]


def file_time(path):
    """Время последнего изменения файла, например «15.11.2026 14:05»."""
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d.%m.%Y %H:%M")
    except OSError:
        return None


# ------------------------------------------------------------------ база читов

def norm(text):
    """Оставляет только буквы и цифры: «Wild_Client.exe» -> «wildclientexe»."""
    return re.sub(r"[^a-zа-яё0-9]", "", (text or "").lower())


def load_base():
    path = os.path.join(base_dir(), "cheats.json")
    with open(path, "r", encoding="utf-8") as file:
        base = json.load(file)
    base["cheat_clients"] = [norm(name) for name in base["cheat_clients"]]
    base["suspicious"] = {norm(word): about for word, about in base["suspicious"].items()}
    base["allowed"] = {norm(word) for word in base.get("allowed", {})}
    base["extensions"] = {ext.lower() for ext in base["extensions"]}
    base["skip_folders"] = {name.lower() for name in base["skip_folders"]}
    return base


def find_word(text, base):
    """
    Ищет в тексте название чита.
    Возвращает (уровень, описание) или (None, None), если ничего нет.
    """
    clean = norm(text)
    for name in base["cheat_clients"]:
        if name in clean:
            return "cheat", f"чит-клиент «{name}»"
    for word in base["allowed"]:
        if word in clean:
            return None, None             # разрешено на сервере, не показываем
    for word, about in base["suspicious"].items():
        if word in clean:
            return "suspicious", about
    return None, None


# ------------------------------------------------------------------ находки

def add(found, level, kind, title, why, where=None, when=None, pid=None):
    """Добавляет находку. Одно и то же место два раза не добавляется."""
    key = (kind, (where or title).lower())
    if any(f["key"] == key for f in found):
        return
    found.append({
        "key": key,
        "level": level,    # "cheat" — точно чит, "suspicious" — стоит проверить
        "kind": kind,      # процесс / файл / папка / недавние / история запусков / защитник
        "title": title,
        "why": why,
        "where": where,
        "when": when,
        "pid": pid,        # номер процесса, чтобы можно было его закрыть
    })


# ------------------------------------------------------------------ проверки
# Каждая проверка добавляет находки в found и возвращает, сколько всего проверила.

PS_PROCESSES = r"""
$t = @{}; foreach ($p in Get-Process) { if ($p.MainWindowTitle) { $t[$p.Id] = $p.MainWindowTitle } }
$r = foreach ($p in Get-CimInstance Win32_Process) {
    [pscustomobject]@{ pid = [int]$p.ProcessId; name = $p.Name; path = $p.ExecutablePath;
                       cmd = $p.CommandLine; title = $t[[int]$p.ProcessId] }
}
ConvertTo-Json -InputObject @($r) -Compress
"""


def check_processes(base, found):
    processes = run_powershell(PS_PROCESSES)
    my_pid = os.getpid()
    for proc in processes:
        if proc.get("pid") in (my_pid, 0, 4):
            continue
        name = proc.get("name") or ""
        title = proc.get("title") or ""
        path = (proc.get("path") or "").removeprefix("\\\\?\\")
        for text, place in ((name, "имя программы"), (title, "заголовок окна"),
                            (proc.get("cmd") or "", "команда запуска")):
            level, about = find_word(text, base)
            if level:
                why = f"запущено прямо сейчас: {about} ({place})"
                if place == "заголовок окна":
                    why += f": «{title}»"
                add(found, level, "процесс", name, why, where=path or None, pid=proc.get("pid"))
                break
    return len(processes)


def walk_folder(root, max_depth, base, found):
    """Обходит папку на max_depth уровней вглубь и ищет файлы и папки с названиями читов."""
    checked = 0
    start = root.rstrip("\\").count("\\")
    for folder, dirs, files in os.walk(root):
        depth = folder.rstrip("\\").count("\\") - start
        keep = []
        for name in dirs:
            if name.lower() in base["skip_folders"]:
                continue
            checked += 1
            full = os.path.join(folder, name)
            level, about = find_word(name, base)
            if level:
                add(found, level, "папка", name, f"в названии: {about}", where=full, when=file_time(full))
                continue          # внутрь найденной папки не заходим, она уже в списке
            keep.append(name)
        dirs[:] = keep if depth < max_depth else []
        for name in files:
            checked += 1
            if os.path.splitext(name)[1].lower() not in base["extensions"]:
                continue
            level, about = find_word(name, base)
            if level:
                full = os.path.join(folder, name)
                add(found, level, "файл", name, f"в названии: {about}", where=full, when=file_time(full))
    return checked


def check_files(base, found):
    checked = 0
    done = set()
    for folder, depth in base["folders"]:
        path = os.path.expandvars(folder)
        if "%" in path or not os.path.isdir(path):
            continue                      # такой папки на этом компьютере нет
        real = os.path.realpath(path).lower()
        if (real, depth) in done:
            continue
        done.add((real, depth))
        checked += walk_folder(path, depth, base, found)
    return checked


def check_recent(base, found):
    recent = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Recent")
    try:
        names = os.listdir(recent)
    except OSError:
        return 0
    for name in names:
        if not name.lower().endswith(".lnk"):
            continue
        level, about = find_word(name[:-4], base)
        if level:
            full = os.path.join(recent, name)
            add(found, level, "недавние", name[:-4],
                f"недавно открывали: {about}. Файл мог быть уже удалён", where=full, when=file_time(full))
    return len(names)


def check_prefetch(base, found):
    if not is_admin():
        return None                       # None значит «не проверено, нужны права»
    folder = os.path.expandvars(r"%SystemRoot%\Prefetch")
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if not name.lower().endswith(".pf"):
            continue
        program = name.rsplit("-", 1)[0]  # «WILDCLIENT.EXE-1A2B3C4D.pf» -> «WILDCLIENT.EXE»
        level, about = find_word(program, base)
        if level:
            add(found, level, "история запусков", program,
                f"эту программу запускали на компьютере: {about}",
                when=file_time(os.path.join(folder, name)))
    return len(names)


PS_DEFENDER = r"""
$m = Get-MpPreference; $r = @()
foreach ($x in @($m.ExclusionPath) + @($m.ExclusionProcess)) { if ($x -and $x -notlike 'N/A*') { $r += [pscustomobject]@{ value = $x } } }
ConvertTo-Json -InputObject @($r) -Compress
"""


def check_defender(base, found):
    if not is_admin():
        return None
    exclusions = run_powershell(PS_DEFENDER)
    for item in exclusions:
        value = str(item.get("value", ""))
        level, about = find_word(value, base)
        if level:
            add(found, level, "защитник", value,
                f"добавлено в исключения Защитника, чтобы антивирус не удалял: {about}")
        elif ".minecraft" in value.lower():
            add(found, "suspicious", "защитник", value,
                "папка Minecraft исключена из проверки Защитником. Так часто прячут читы")
    return len(exclusions)


STEPS = [
    ("Проверяю запущенные программы", "processes", check_processes),
    ("Проверяю файлы и папки", "files", check_files),
    ("Проверяю недавние файлы", "recent", check_recent),
    ("Проверяю историю запусков", "prefetch", check_prefetch),
    ("Проверяю исключения Защитника", "defender", check_defender),
]


def scan(base, show_animation=True):
    """Запускает все проверки по очереди с крутящимся значком. Возвращает (находки, счётчики)."""
    found = []
    counts = {}
    spinner = "|/-\\"
    for number, (title, key, check) in enumerate(STEPS, 1):
        box = {}
        worker = threading.Thread(target=lambda: box.update(result=check(base, found)), daemon=True)
        worker.start()
        frame = 0
        while worker.is_alive():
            if show_animation:
                sys.stdout.write(f"\r{CYAN}  [{number}/{len(STEPS)}] {title} {spinner[frame % 4]}{RESET}      ")
                sys.stdout.flush()
            frame += 1
            time.sleep(0.12)
        counts[key] = box.get("result")
        sys.stdout.write(f"\r  {GREEN}[{number}/{len(STEPS)}] {title} ✓{RESET}      \n")
        sys.stdout.flush()
    found.sort(key=lambda f: 0 if f["level"] == "cheat" else 1)
    return found, counts


# ------------------------------------------------------------------ экраны

def count_text(value):
    return f"{value}" if value is not None else "нужны права админа"


def report_lines(found, counts):
    cheats = sum(1 for f in found if f["level"] == "cheat")
    suspicious = len(found) - cheats
    if cheats:
        verdict = RED + BOLD + "НАЙДЕНЫ ЧИТЫ" + RESET
    elif suspicious:
        verdict = YELLOW + BOLD + "ЕСТЬ ПОДОЗРИТЕЛЬНОЕ" + RESET
    else:
        verdict = GREEN + BOLD + "ЧИТЫ НЕ НАЙДЕНЫ" + RESET
    lines = [
        f"  Программ: {count_text(counts.get('processes'))},  файлов и папок: {count_text(counts.get('files'))},"
        f"  недавних: {count_text(counts.get('recent'))}",
        f"  История запусков: {count_text(counts.get('prefetch'))},"
        f"  исключений Защитника: {count_text(counts.get('defender'))}",
        "",
        f"  {verdict}   {RED}читов {cheats}{RESET},  {YELLOW}подозрительного {suspicious}{RESET}",
        line(),
    ]
    for number, f in enumerate(found, 1):
        badge = RED + BOLD + "ЧИТ" + RESET if f["level"] == "cheat" else YELLOW + BOLD + "ПОДОЗРИТЕЛЬНО" + RESET
        lines.append(f"  {BOLD}[{number}]{RESET} {badge}  {CYAN}{f['title']}{RESET}  {GRAY}{f['kind']}{RESET}")
        if f["where"]:
            lines.append(f"      Где:     {f['where']}")
        if f["when"]:
            lines.append(f"      Когда:   {f['when']}")
        lines.append(f"      Почему:  {f['why']}")
        lines.append("")
    return lines


def save_report(found, counts):
    name = datetime.now().strftime("проверка_%Y-%m-%d_%H-%M-%S.txt")
    path = os.path.join(base_dir(), name)
    with open(path, "w", encoding="utf-8") as file:
        file.write(f"Cheat Search — отчёт от {datetime.now():%d.%m.%Y %H:%M}\n")
        file.write(f"Компьютер: {os.environ.get('COMPUTERNAME', '?')}\n\n")
        for text in report_lines(found, counts):
            file.write(strip_colors(text) + "\n")
    return path


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def to_recycle_bin(path):
    """Отправляет файл или папку в Корзину (не удаляет навсегда). True, если получилось."""
    operation = SHFILEOPSTRUCTW()
    operation.wFunc = 3                       # FO_DELETE
    operation.pFrom = path + "\0"             # путь должен заканчиваться двумя нулями
    operation.fFlags = 0x40 | 0x10 | 0x04 | 0x400   # в Корзину, без вопросов, тихо, без окон ошибок
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    return result == 0 and not os.path.exists(path)


def kill_process(pid):
    result = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True, creationflags=0x08000000)
    return result.returncode == 0


def can_remove(f):
    """Что можно убрать кнопкой [4]: только то, что точно чит."""
    if f["level"] != "cheat":
        return False
    if f["kind"] == "процесс":
        return bool(f["pid"])
    return f["kind"] in ("файл", "папка") and bool(f["where"]) and os.path.exists(f["where"])


def remove_cheats(found):
    """Закрывает запущенные читы и отправляет чит-файлы в Корзину. Возвращает текст для экрана."""
    targets = [f for f in found if can_remove(f)]
    if not targets:
        return YELLOW + "Удалять нечего: нет найденных чит-файлов или запущенных читов." + RESET
    print()
    print(f"  {BOLD}Будет удалено:{RESET}")
    for f in targets:
        action = "закрыть" if f["kind"] == "процесс" else "в Корзину"
        print(f"    {RED}•{RESET} {f['title']}  {GRAY}({action}){RESET}")
    print(f"\n  Точно удалить? {BOLD}[Y]{RESET} да   {BOLD}[N]{RESET} нет")
    if read_key({"y", "Y", "n", "N", "н", "Н", "т", "Т"}) not in ("y", "Y", "н", "Н"):
        return GRAY + "Отменено, ничего не удалено." + RESET

    done, failed = [], []
    # сначала закрываем процессы, иначе их файлы заняты и не удалятся
    for f in sorted(targets, key=lambda f: 0 if f["kind"] == "процесс" else 1):
        ok = kill_process(f["pid"]) if f["kind"] == "процесс" else to_recycle_bin(f["where"])
        (done if ok else failed).append(f)
    found[:] = [f for f in found if f not in done]
    message = GREEN + f"Удалено: {len(done)}." + RESET
    if failed:
        message += YELLOW + f" Не получилось: {len(failed)} (попробуй с правами администратора)." + RESET
    return message


def open_folder(path):
    if path and os.path.exists(path):
        subprocess.Popen(f'explorer /select,"{path}"')
        return True
    return False


def results_screen(found, counts):
    message = ""
    while True:
        clear()
        print(logo())
        print(line())
        for text in report_lines(found, counts):
            print(text)
        print(line())
        print(f"  {BOLD}[1]{RESET} Открыть папку   {BOLD}[2]{RESET} Назад в главное меню   {BOLD}[3]{RESET} Сохранить отчёт")
        print(f"  {BOLD}[4]{RESET} Удалить найденные читы")
        if message:
            print("\n  " + message)
        key = read_key({"1", "2", "3", "4"})
        if key == "2":
            return
        if key == "4":
            message = remove_cheats(found)
            if not found:
                return
            continue
        if key == "3":
            message = GREEN + "Отчёт сохранён: " + save_report(found, counts) + RESET
        if key == "1":
            answer = "1" if len(found) == 1 else input(f"\n  Номер находки (1-{len(found)}): ").strip()
            if not answer.isdigit() or not 1 <= int(answer) <= len(found):
                message = YELLOW + "Нет такого номера." + RESET
                continue
            chosen = found[int(answer) - 1]
            if open_folder(chosen["where"]):
                message = GREEN + "Открыл папку: " + chosen["where"] + RESET
            else:
                message = YELLOW + "Файла уже нет на диске или путь неизвестен." + RESET


def main_menu(base):
    status = ""
    while True:
        clear()
        print(logo())
        print(line())
        print(f"  {BOLD}[1]{RESET}  Начать проверку")
        print(f"  {BOLD}[2]{RESET}  Выход")
        admin = is_admin()
        if not admin:
            print(f"  {BOLD}[3]{RESET}  Перезапустить с правами администратора")
        print(line())
        if status:
            print("  " + status)
        if not admin:
            print(f"  {YELLOW}Без прав администратора не проверяются история запусков{RESET}")
            print(f"  {YELLOW}и исключения Защитника. Для полной проверки нажми 3.{RESET}")

        key = read_key({"1", "2", "3"} if not admin else {"1", "2"})
        if key == "2":
            clear()
            return
        if key == "3":
            if relaunch_as_admin():
                return
            status = YELLOW + "Не удалось получить права администратора." + RESET
            continue

        clear()
        print(logo())
        print(line())
        print()
        found, counts = scan(base)
        when = datetime.now().strftime("%H:%M")
        if found:
            results_screen(found, counts)
            status = f"{GRAY}Последняя проверка в {when}: найдено {len(found)}.{RESET}"
        else:
            status = f"{GREEN}✓ Проверка в {when}: читы не найдены.{RESET}"


def main():
    if os.name != "nt":
        print("Cheat Search работает только в Windows.")
        return
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    enable_colors()
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("Cheat Search")
    except Exception:
        pass
    try:
        base = load_base()
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print(f"{RED}Не удалось прочитать cheats.json: {error}{RESET}")
        print("Файл cheats.json должен лежать рядом с cheat_search.py.")
        input("Нажми Enter, чтобы выйти...")
        return

    if "--scan" in sys.argv:
        found, counts = scan(base, show_animation=sys.stdout.isatty())
        print()
        for text in report_lines(found, counts):
            print(text)
        sys.exit(1 if any(f["level"] == "cheat" for f in found) else 0)

    try:
        main_menu(base)
    except KeyboardInterrupt:
        clear()


if __name__ == "__main__":
    main()
