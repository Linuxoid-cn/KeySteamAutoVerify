# -*- coding: utf-8 -*-
"""用独立浏览器 profile + CDP 拿登录后的 cookie（不读数据库，绕开文件锁）。

为什么换这套：
    Chromium 系浏览器运行时会**独占** cookie 数据库文件（WinError 32），
    普通方式读不到。而新开一个独立 profile 并加 --remote-debugging-port，
    就能通过 DevTools 协议直接问浏览器要 cookie —— 完全不受文件锁影响，
    也不需要用户去关浏览器、不影响他日常使用的 profile。

流程：
    1. 用独立 profile 目录（默认 %TEMP%/ksav/profile）启动 Chrome/Edge
    2. 打开夸克登录页，用户在窗口里正常登录
    3. 通过 CDP Network.getAllCookies 拿到 cookie
    4. 命中关键 cookie 后收工，可选自动关掉这个浏览器窗口
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.request

# 判定"已登录"的关键 cookie
# 注意：夸克实际用的是**双下划线**前缀（__kps / __puus / __uid），
# 不带下划线的 kps/puus 在登录后并不存在 —— 这点是实测出来的。
LOGIN_KEYS = ("__kps", "__puus", "__uid", "__kp", "__pus",
              "kps", "puus", "p_uid", "b-user-id", "sid")
# 其中最核心的几个（出现任意一个就够）
CORE_KEYS = ("__kps", "__puus", "__uid", "kps", "puus")


class CookieError(RuntimeError):
    pass


# ------------------------------------------------------------------ 浏览器
def _candidates() -> list[tuple[str, str]]:
    """返回 [(名字, 可执行文件路径)]。"""
    out = []
    for name, paths in (
        ("Chrome", [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]),
        ("Edge", [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]),
    ):
        for p in paths:
            if os.path.exists(p):
                out.append((name, p))
                break
    # 夸克浏览器（若有）
    for base in (r"C:\Program Files", r"C:\Program Files (x86)"):
        for sub in ("Quark", "QuarkBrowser"):
            d = os.path.join(base, sub)
            if os.path.isdir(d):
                for root, _dirs, files in os.walk(d):
                    for f in files:
                        if f.lower() in ("quark.exe", "quarkbrowser.exe"):
                            out.append(("Quark", os.path.join(root, f)))
                            break
    return out


def _profile_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "ksav", "profile")
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------ CDP
def _cdp_list(port: int) -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return []


def _cdp_cookies(port: int) -> dict:
    """通过 CDP 取全部 cookie -> {name: value}（优先 quark/uc 域）。"""
    pages = [t for t in _cdp_list(port) if t.get("type") == "page"]
    if not pages:
        return {}
    ws_url = pages[0].get("webSocketDebuggerUrl")
    if not ws_url:
        return {}

    import websocket
    ws = websocket.create_connection(ws_url, timeout=10)
    try:
        msg_id = 1
        payload = {"id": msg_id, "method": "Network.getAllCookies", "params": {}}
        ws.send(json.dumps(payload))
        for _ in range(40):
            raw = ws.recv()
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("id") == msg_id:
                cookies = (data.get("result") or {}).get("cookies") or []
                out = {}
                # 先收夸克/UC 的，再补其他的
                for c in sorted(cookies,
                                key=lambda x: 0 if ("quark" in x.get("domain", "")
                                                    or "uc.cn" in x.get("domain", "")) else 1):
                    n = c.get("name")
                    if not n:
                        continue
                    out.setdefault(n, c.get("value", ""))
                return out
        return {}
    finally:
        try:
            ws.close()
        except Exception:
            pass


def looks_logged_in(cookies: dict) -> bool:
    if not cookies:
        return False
    # 有任意一个核心会话 cookie 就算登录了
    if any(cookies.get(k) for k in CORE_KEYS):
        return True
    # 或者命中两个以上登录相关 cookie
    return len([k for k in LOGIN_KEYS if cookies.get(k)]) >= 2


# ------------------------------------------------------------------ 主流程
def login_and_capture(cookies_path: str,
                      url: str = "https://pan.quark.cn/",
                      timeout: float = 240.0,
                      port: int = 9333,
                      keep_open: bool = False,
                      log=print,
                      progress=None) -> dict | None:
    """开独立 profile 的浏览器 → 用户登录 → CDP 导出 cookie → 存盘。"""
    cands = _candidates()
    if not cands:
        raise CookieError("没找到 Chrome/Edge 浏览器")

    profile = _profile_dir()
    # 清掉上次的残留锁
    for f in ("SingletonLock", "SingletonCookie", "SingletonSocket",
              "lockfile"):
        try:
            os.remove(os.path.join(profile, f))
        except Exception:
            pass

    proc = None
    browser_name = ""
    for name, exe in cands:
        args = [
            exe,
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            url,
        ]
        log(f"[浏览器] 用 {name} 打开独立窗口（不影响你日常浏览）")
        try:
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            browser_name = name
            break
        except Exception as e:
            log(f"[浏览器] 启动 {name} 失败: {e}")

    if proc is None:
        raise CookieError("浏览器启动失败")

    log("[浏览器] 请在刚打开的窗口里登录夸克（扫码或账号密码都行）")
    log(f"[浏览器] 登录后会自动继续，最多等 {int(timeout)} 秒…")

    deadline = time.time() + timeout
    cookies: dict = {}
    last_note = 0.0
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                log("[浏览器] 窗口已被关闭")
                break
            c = _cdp_cookies(port)
            if looks_logged_in(c):
                cookies = c
                break
            now = time.time()
            remain = int(deadline - now)
            if progress is not None:
                try:
                    progress(remain, len(c))
                except Exception:
                    pass
            elif now - last_note > 15:
                last_note = now
                log(f"[浏览器] 等待登录中…（剩余 {remain}s，"
                    f"当前 cookie {len(c)} 个）")
            time.sleep(2.5)
    finally:
        if progress is not None:
            try:
                from . import console_ui
                console_ui.end_line()
            except Exception:
                print()
        if cookies:
            save(cookies_path, cookies, log)
            log(f"[浏览器] 已捕获 {len(cookies)} 个 cookie → "
                f"{os.path.basename(cookies_path)}")
        if not keep_open:
            try:
                proc.terminate()
            except Exception:
                pass
            time.sleep(1)
            try:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=10)
            except Exception:
                pass

    return cookies or None


def save(path: str, cookies: dict, log=print) -> None:
    ordered = {}
    for k in LOGIN_KEYS:
        if k in cookies:
            ordered[k] = cookies[k]
    for k, v in cookies.items():
        if k not in ordered:
            ordered[k] = v
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)


def try_existing_profile() -> dict:
    """快速路径：浏览器没在跑时，直接读默认 profile 的 cookie 库。"""
    from . import browser_cookie
    try:
        _name, c = browser_cookie.export_from_any()
        return c
    except Exception:
        return {}
