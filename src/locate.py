# -*- coding: utf-8 -*-
"""定位 KeySteam 的安装位置 —— 换台机器、换个安装盘也不用改配置。

查找顺序（命中即返回）：
    1. config.json 里显式写的路径（存在就用，作为用户手动覆盖）
    2. 正在运行的 keysteam.exe 的镜像路径（最可信：就是当前这个实例）
    3. 注册表卸载项 HKCU / HKLM / WOW6432Node 的 DisplayIcon / InstallLocation
    4. 注册表 App Paths\\keysteam.exe
    5. 常见安装目录（%LOCALAPPDATA%\\KeySteam、Program Files\\KeySteam 等）
    6. PATH 里的 keysteam.exe

返回 (路径, 来源说明)；一个都没找到返回 (None, "")。
全部只用标准库：winreg + ctypes + tasklist。
"""
from __future__ import annotations

import os
import subprocess
import sys

EXE_NAME = "keysteam.exe"
DISPLAY_HINTS = ("keysteam", "key steam", "keysteam 验证")

IS_WIN = sys.platform == "win32"

if IS_WIN:
    try:
        import winreg  # type: ignore
    except Exception:      # 极端情况下（精简运行时）退化为只用路径探测
        winreg = None       # type: ignore
else:
    winreg = None           # type: ignore


# ------------------------------------------------------------------ 小工具
def _norm(path: str) -> str:
    """把 "C:\\x\\keysteam.exe,0" / 带引号的注册表值清理成干净路径。"""
    if not path:
        return ""
    p = str(path).strip().strip('"')
    p = p.split(",")[0].strip().strip('"')     # DisplayIcon 常带 ",0"
    return p


def _exe_in_dir(d: str) -> str:
    """目录里有没有 keysteam.exe（大小写不敏感）。"""
    if not d or not os.path.isdir(d):
        return ""
    want = EXE_NAME.lower()
    for name in (EXE_NAME, "KeySteam.exe"):
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
    try:
        for name in os.listdir(d):
            if name.lower() == want and os.path.isfile(os.path.join(d, name)):
                return os.path.join(d, name)
    except OSError:
        pass
    return ""


def _ok(path: str) -> str:
    """只认真实存在的 .exe。"""
    p = _norm(path)
    return p if p and p.lower().endswith(".exe") and os.path.isfile(p) else ""


# ------------------------------------------------------------------ 进程
def _pids() -> list[int]:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq " + EXE_NAME, "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
            encoding="mbcs", errors="ignore",
        ).stdout or ""
    except Exception:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == EXE_NAME:
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def _process_image(pid: int) -> str:
    """拿某个 pid 的可执行文件完整路径（QueryFullProcessImageName）。"""
    if not IS_WIN:
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(2048)
            size = wintypes.DWORD(2048)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            k32.CloseHandle(h)
    except Exception:
        return ""


def from_process() -> str:
    for pid in _pids():
        p = _process_image(pid)
        if _ok(p):
            return p
    return ""


# ------------------------------------------------------------------ 注册表
def _uninstall_roots():
    if not winreg:
        return []
    roots = []
    for hive, name in ((winreg.HKEY_CURRENT_USER, "HKCU"),
                       (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
                       (winreg.HKEY_LOCAL_MACHINE, "HKLM-WOW64")):
        for flag in (0, getattr(winreg, "KEY_WOW64_64KEY", 0),
                     getattr(winreg, "KEY_WOW64_32KEY", 0)):
            roots.append((hive, flag,
                          r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                          name))
    return roots


def _iter_uninstall_entries():
    """遍历卸载项，产出 (display_name, install_location, display_icon, version)。"""
    if not winreg:
        return
    seen = set()
    for hive, flag, sub, _name in _uninstall_roots():
        try:
            key = winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | flag)
        except OSError:
            continue
        try:
            n = winreg.QueryInfoKey(key)[0]
            for i in range(n):
                try:
                    child = winreg.OpenKey(key, winreg.EnumKey(key, i), 0,
                                           winreg.KEY_READ | flag)
                except OSError:
                    continue
                with child:
                    vals = {}
                    for field in ("DisplayName", "InstallLocation",
                                  "DisplayIcon", "DisplayVersion"):
                        try:
                            vals[field] = winreg.QueryValueEx(child, field)[0]
                        except OSError:
                            vals[field] = ""
                    dn = str(vals.get("DisplayName") or "")
                    low = dn.lower()
                    if not any(h in low for h in DISPLAY_HINTS):
                        continue
                    sig = (dn, vals.get("InstallLocation"), vals.get("DisplayIcon"))
                    if sig in seen:
                        continue
                    seen.add(sig)
                    yield (dn,
                           str(vals.get("InstallLocation") or ""),
                           str(vals.get("DisplayIcon") or ""),
                           str(vals.get("DisplayVersion") or ""))
        finally:
            key.Close()


def from_registry(log=print) -> str:
    # 3) 卸载项：DisplayIcon 最准（直接指 exe），其次 InstallLocation
    for dn, loc, icon, ver in _iter_uninstall_entries():
        p = _ok(icon)
        if p:
            log(f"[定位] 注册表卸载项「{dn}」"
                f"{' v' + ver if ver else ''} → {p}")
            return p
        p = _exe_in_dir(_norm(loc))
        if p:
            log(f"[定位] 注册表安装目录「{dn}」→ {p}")
            return p

    # 4) App Paths
    if winreg:
        for hive, name in ((winreg.HKEY_CURRENT_USER, "HKCU"),
                           (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
            for exename in (EXE_NAME, "KeySteam.exe"):
                sub = (r"Software\Microsoft\Windows\CurrentVersion\App Paths\\"
                       + exename)
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        p = _ok(str(winreg.QueryValueEx(k, "")[0]))
                except OSError:
                    continue
                if p:
                    log(f"[定位] 注册表 App Paths（{name}）→ {p}")
                    return p
    return ""


def from_common_dirs() -> str:
    env = os.environ
    cands = [
        os.path.join(env.get("LOCALAPPDATA", ""), "KeySteam"),
        os.path.join(env.get("LOCALAPPDATA", ""), "Programs", "KeySteam"),
        os.path.join(env.get("APPDATA", ""), "KeySteam"),
        os.path.join(env.get("PROGRAMFILES", ""), "KeySteam"),
        os.path.join(env.get("PROGRAMFILES(X86)", ""), "KeySteam"),
        os.path.join(env.get("PROGRAMDATA", ""), "KeySteam"),
        os.path.join(env.get("LOCALAPPDATA", ""), "Programs", "key-steam"),
    ]
    for d in cands:
        p = _exe_in_dir(d)
        if p:
            return p
    return ""


def from_path() -> str:
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        p = _exe_in_dir(d.strip())
        if p:
            return p
    return ""


# ------------------------------------------------------------------ 对外
LABELS = {
    "config": "config.json（或默认路径）",
    "process": "正在运行的进程",
    "registry": "注册表",
    "common": "常见安装目录",
    "path": "PATH 环境变量",
}


def describe(how: str) -> str:
    """把来源代号翻译成人话。"""
    return LABELS.get(how, how or "未知")


def find(config_path: str = "", log=print) -> tuple[str, str]:
    """返回 (exe 路径, 来源)。找不到返回 ("", "")。"""
    p = _ok(config_path)
    if p:
        return p, "config"

    p = from_process()
    if p:
        return p, "process"

    p = from_registry(log)
    if p:
        return p, "registry"

    p = from_common_dirs()
    if p:
        return p, "common"

    p = from_path()
    if p:
        return p, "path"

    return "", ""


def install_hint() -> str:
    """找不到时给人看的一句话。"""
    return ("没找到 KeySteam 的安装位置。请先安装并运行一次 KeySteam，"
            "或在 config.json 里把 keysteam_exe 写成完整路径"
            r"（例如 C:\Users\你\AppData\Local\KeySteam\keysteam.exe）。")
