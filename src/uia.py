# -*- coding: utf-8 -*-
"""通过 Windows UI Automation 操作 KeySteam 的 WebView2 界面。

为什么用 UIA 而不是 CDP：
    Tauri 会设置自己的 AdditionalBrowserArguments，导致
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 环境变量被忽略，开不出调试端口。
    而 WebView2 会把 DOM 映射成 UIA 无障碍树，控件带语义名称和精确矩形。

实测稳定锚点（KeySteam 3.3.2）：
    WindowControl  Name 含 "KeySteam 验证"
    ImageControl   Name 含 "二维码"         368x369
    EditControl    Name 含 "验证码"/"6 位"  （placeholder 会变成 Name）
    ButtonControl  Name == "验证"
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional

import uiautomation as auto

# 高 DPI 下坐标才是真实屏幕坐标
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32

GATE_KEYWORD = "KeySteam 验证"
QR_KEYWORD = "二维码"
CODE_KEYWORDS = ("验证码", "6 位", "6位", "数字")
SUBMIT_TEXT = "验证"


# ------------------------------------------------------------------ 树遍历
def walk(el, max_depth: int = 16, _depth: int = 0):
    if _depth > max_depth:
        return
    try:
        kids = el.GetChildren()
    except Exception:
        return
    for k in kids:
        yield _depth, k
        yield from walk(k, max_depth, _depth + 1)


def collect(host, max_depth: int = 16) -> list:
    out = []
    for d, c in walk(host, max_depth):
        try:
            r = c.BoundingRectangle
            out.append({
                "ctl": c,
                "depth": d,
                "type": c.ControlTypeName,
                "name": (c.Name or ""),
                "x": r.left, "y": r.top,
                "w": r.right - r.left, "h": r.bottom - r.top,
            })
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- Win32 枚举
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)



def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    try:
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def _pid_image_name(pid: int) -> str:
    """用 QueryFullProcessImageNameW 拿进程可执行文件名（小写）。"""
    if not pid:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            import os as _os
            return _os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def _is_target_window(hwnd: int, title: str = "KeySteam") -> bool:
    """是不是 KeySteam 的窗口：进程名必须是 keysteam.exe。"""
    name = _pid_image_name(_window_pid(hwnd))
    if name == "keysteam.exe":
        return True
    return False


def _enum_top_windows() -> list[tuple[int, str, str]]:
    """枚举所有顶层窗口 -> [(hwnd, class, title)]"""
    out: list[tuple[int, str, str]] = []

    def _cb(hwnd, _l):
        try:
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            ttl = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, ttl, 512)
            out.append((int(hwnd or 0), cls.value, ttl.value))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(_cb), None)
    except Exception:
        pass
    return out


def find_main_window(timeout: float = 20.0, title: str = "KeySteam"):
    """找 KeySteam 主窗口。

    判据用「进程可执行文件名 == keysteam.exe」而不是窗口标题或类名，
    因为本工具自己和 DSH 都可能是 Tauri 窗口，只靠类名会认错。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd, cls, ttl in _enum_top_windows():
            if not hwnd:
                continue
            if cls != "Tauri Window":
                continue
            if not _is_target_window(hwnd, title):
                continue
            try:
                ctl = auto.ControlFromHandle(hwnd)
                if ctl is not None:
                    return ctl
            except Exception:
                continue
        time.sleep(0.4)
    return None


def main_window_handle() -> int:
    for hwnd, cls, _t in _enum_top_windows():
        if hwnd and cls == "Tauri Window" and _is_target_window(hwnd):
            return hwnd
    return 0


# ------------------------------------------------------------------ 渲染宿主
EnumChildProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def _find_child_by_class(parent_hwnd: int, class_name: str) -> Optional[int]:
    found: list[int] = []

    def _cb(hwnd, _l):
        try:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == class_name:
                found.append(int(hwnd or 0))
                return False
        except Exception:
            pass
        return True

    try:
        user32.EnumChildWindows(ctypes.c_void_p(parent_hwnd),
                                EnumChildProc(_cb), None)
    except Exception:
        pass
    return found[0] if found else None


def find_render_host(win):
    """精确拿到 Chrome_RenderWidgetHostHWND —— DOM 无障碍树的根。"""
    try:
        hwnd = win.NativeWindowHandle
    except Exception:
        hwnd = 0
    if not hwnd:
        hwnd = main_window_handle()
    if not hwnd:
        return None
    target = _find_child_by_class(int(hwnd), "Chrome_RenderWidgetHostHWND")
    if not target:
        return None
    try:
        return auto.ControlFromHandle(target)
    except Exception:
        return None


# ------------------------------------------------------------------ 语义定位
def find_gate(items: list) -> Optional[dict]:
    for it in items:
        if it["type"] == "WindowControl" and GATE_KEYWORD in it["name"]:
            return it
    return None


def find_qr(items: list, gate: Optional[dict] = None) -> Optional[dict]:
    gx = gy = gw = gh = None
    if gate:
        gx, gy, gw, gh = gate["x"], gate["y"], gate["w"], gate["h"]

    best, best_score = None, 0.0
    for it in items:
        if it["type"] != "ImageControl":
            continue
        w, h = it["w"], it["h"]
        if w < 120 or h < 120:
            continue
        ratio = w / max(1, h)
        if ratio < 0.75 or ratio > 1.35:
            continue
        if gx is not None:
            if not (gx <= it["x"] and it["x"] + w <= gx + gw and
                    gy <= it["y"] and it["y"] + h <= gy + gh):
                continue
        score = float(w * h) * (3.0 if QR_KEYWORD in it["name"] else 1.0)
        if score > best_score:
            best, best_score = it, score
    return best


def find_code_input(items: list, gate: Optional[dict] = None) -> Optional[dict]:
    cands = [it for it in items if it["type"] == "EditControl"]
    if gate:
        gx, gy, gw, gh = gate["x"], gate["y"], gate["w"], gate["h"]
        inside = [c for c in cands
                  if gx <= c["x"] <= gx + gw and gy <= c["y"] <= gy + gh]
        if inside:
            cands = inside
    for c in cands:
        if any(k in c["name"] for k in CODE_KEYWORDS):
            return c
    if cands:
        return max(cands, key=lambda c: c["y"])
    return None


def find_submit_button(items: list, input_el: Optional[dict],
                       gate: Optional[dict] = None) -> Optional[dict]:
    btns = [it for it in items
            if it["type"] == "ButtonControl" and it["name"].strip() == SUBMIT_TEXT]
    if not btns and gate:
        gx, gy, gw, gh = gate["x"], gate["y"], gate["w"], gate["h"]
        btns = [it for it in items
                if it["type"] == "ButtonControl"
                and SUBMIT_TEXT in it["name"]
                and gx <= it["x"] <= gx + gw]

    if input_el is not None and btns:
        iy = input_el["y"] + input_el["h"] // 2
        tol = max(30, input_el["h"])
        same_row = [b for b in btns
                    if abs((b["y"] + b["h"] // 2) - iy) <= tol
                    and b["x"] >= input_el["x"]]
        if same_row:
            return min(same_row, key=lambda b: b["x"])

    if btns:
        return min(btns, key=lambda b: b["w"] * b["h"])
    return None


# ------------------------------------------------------------------ 动作
def set_edit_value(el, text: str) -> bool:
    ctl = el["ctl"] if isinstance(el, dict) else el
    try:
        ctl.GetValuePattern().SetValue(text)
        return True
    except Exception:
        pass
    try:
        ctl.Click(simulateMove=False)
        time.sleep(0.2)
        ctl.SendKeys("{Ctrl}a{Delete}", waitTime=0.05)
        ctl.SendKeys(text, waitTime=0.02)
        return True
    except Exception:
        return False


def read_edit_value(el) -> str:
    ctl = el["ctl"] if isinstance(el, dict) else el
    try:
        return ctl.GetValuePattern().Value or ""
    except Exception:
        return ""


def click_element(el) -> bool:
    ctl = el["ctl"] if isinstance(el, dict) else el
    try:
        ctl.GetInvokePattern().Invoke()
        return True
    except Exception:
        pass
    try:
        ctl.Click(simulateMove=False)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ 状态
def snapshot(host) -> dict:
    items = collect(host)
    gate = find_gate(items)
    qr = find_qr(items, gate)
    code_input = find_code_input(items, gate)
    btn = find_submit_button(items, code_input, gate)
    texts = [it["name"] for it in items
             if it["type"] == "TextControl" and it["name"]]
    return {
        "items": items,
        "gate": gate,
        "qr": qr,
        "input": code_input,
        "button": btn,
        "gate_visible": bool(gate is not None),
        "text": " ".join(texts)[:3000],
    }
