# -*- coding: utf-8 -*-
"""浏览器登录引导：打开浏览器 → 等用户登录夸克 → 自动把 cookie 导成 json。

流程：
    1. 用系统默认浏览器打开 https://pan.quark.cn/（或分享页）
    2. 用户在浏览器里正常登录 / 扫码
    3. 程序轮询各浏览器的 cookie 数据库，一旦发现有效的夸克登录态
       （kps / puus 这类关键 cookie 出现），立刻导出并写入 cookies.json
    4. 导完立即继续原流程，不需要用户再操作

对"已经在浏览器登录过"的用户，第 3 步会在几秒内命中。
"""
from __future__ import annotations

import json
import os
import time
import webbrowser
from typing import Optional

from . import browser_cookie

# 判定"已登录"的关键 cookie（夸克登录态里一定会出现）
LOGIN_KEYS = ("kps", "puus", "p_uid", "b-user-id", "sid")

QUARK_HOME = "https://pan.quark.cn/"


def looks_logged_in(cookies: dict) -> bool:
    if not cookies:
        return False
    hit = [k for k in LOGIN_KEYS if cookies.get(k)]
    # kps 是最核心的会话 cookie
    return bool(cookies.get("kps")) or len(hit) >= 2


def pick_browser(log=print):
    """选一个可用的浏览器来读取 cookie。

    优先选"不在运行"的（数据库能直接读），否则选默认浏览器并在需要时提示。
    """
    from . import browser_cookie
    avail = [(n, ud, exe) for n, ud, exe in browser_cookie.browser_userdata() if ud]
    if not avail:
        return None
    # 先看有没有没在跑的
    for name, ud, exe in avail:
        if not browser_cookie.browser_running(name):
            return (name, ud, exe)
    # 都开着：挑 Chrome/Edge 里第一个
    return avail[0]


def open_login_page(url: str = QUARK_HOME, log=print, browser=None) -> None:
    """用指定浏览器打开链接；不指定就用系统默认。"""
    log(f"[浏览器] 正在打开 {url}")
    if browser:
        name, _ud, exe = browser
        if exe and os.path.exists(exe):
            try:
                import subprocess
                # 不要 --incognito：要写进持久 profile 才好导出
                subprocess.Popen([exe, url], close_fds=True)
                log(f"[浏览器] 已用 {name} 打开")
                return
            except Exception as e:
                log(f"[浏览器] 启动 {name} 失败: {e}")
    try:
        webbrowser.open(url)
    except Exception as e:
        log(f"[浏览器] 打开失败: {e}，请手动复制链接到浏览器")


def _try_export_any(log=print):
    from . import browser_cookie
    for name, ud, _exe in browser_cookie.browser_userdata():
        if not ud:
            continue
        try:
            c = browser_cookie.export_cookies(ud)
        except Exception:
            continue
        if c:
            return name, c
    return "", {}


def wait_and_export(cookies_path: str,
                    url: str = QUARK_HOME,
                    timeout: float = 180.0,
                    interval: float = 3.0,
                    log=print) -> Optional[dict]:
    """打开浏览器 → 等登录 → 导出 cookie 存盘 → 返回 cookies。

    超时返回 None。用户中途自己关掉浏览器也没关系，
    只要之前登录过就能导出。
    """
    browser = pick_browser(log)
    if browser:
        log(f"[浏览器] 选定 {browser[0]}（读取它的 cookie）")
    open_login_page(url, log, browser)
    log("[浏览器] 请在浏览器里登录夸克（扫码或账号密码都行）")
    log(f"[浏览器] 登录完成后会自动继续，最多等 {int(timeout)} 秒…")

    deadline = time.time() + timeout
    last_note = 0.0
    while time.time() < deadline:
        browser, cookies = _try_export_any(log)

        if cookies and looks_logged_in(cookies):
            save(cookies_path, cookies, log)
            log(f"[浏览器] 已从 {browser} 导出 {len(cookies)} 个 cookie")
            log(f"[浏览器] 已保存到 {os.path.basename(cookies_path)}")
            return cookies

        now = time.time()
        if now - last_note > 15:
            last_note = now
            left = int(deadline - now)
            log(f"[浏览器] 还在等你登录…（剩余 {left}s）")
        time.sleep(interval)

    log("[浏览器] 等待超时，没检测到登录状态")
    return None


def save(path: str, cookies: dict, log=print) -> None:
    """把 cookie 写进 json（保持 kps/puus 在前，便于人工检查）。"""
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
    try:
        # 只给当前用户读写
        os.chmod(path, 0o600)
    except Exception:
        pass


def try_silent(path: str, log=print) -> Optional[dict]:
    """不打开浏览器，直接尝试从已登录的浏览器里导出（快速路径）。"""
    browser, cookies = _try_export_any(log)
    if cookies and looks_logged_in(cookies):
        save(path, cookies, log)
        log(f"[浏览器] 直接从 {browser} 导出了 {len(cookies)} 个 cookie")
        return cookies
    return None
