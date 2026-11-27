# -*- coding: utf-8 -*-
"""界面操作统一入口。

    非打包（python 直接跑） -> 用 uiautomation（快，一次调用几毫秒）
    打包成 exe            -> 用 PowerShell + .NET UIA（稳，一次几百毫秒）

原因：PyInstaller 打包后 comtypes 的 IUIAutomation 会退化
      （ElementFromHandle 正常，但 GetFirstChildElement 恒为 NULL），
      而 PowerShell 的 .NET UIA 在同一台机器上完全正常。
"""
from __future__ import annotations

import os
import sys

_FROZEN = bool(getattr(sys, "frozen", False))
FORCE_PS = os.environ.get("KSAV_PS", "") == "1"
USE_PS = _FROZEN or FORCE_PS

if USE_PS:
    from . import uia_ps as _ps
else:
    from . import uia as _native


# ------------------------------------------------------------------ 窗口
def window_handle() -> int:
    if USE_PS:
        # Win32 枚举在任何模式下都可靠，直接借原生实现
        from . import uia as _u
        return _u.main_window_handle()
    return _native.main_window_handle()


def find_window(timeout: float = 20.0):
    if USE_PS:
        from . import uia as _u
        return _u.find_main_window(timeout)
    return _native.find_main_window(timeout)


# ------------------------------------------------------------------ 状态
def snapshot() -> dict:
    """返回 {gate_visible, qr, input, button, text, total}，元素都是纯字典。"""
    if USE_PS:
        r = _ps.run("find", {"hwnd": window_handle()})
        ok = bool(r.get("ok"))
        def _clean(d):
            if not d:
                return None
            return {
                "idx": d.get("idx"),
                "type": d.get("type"),
                "name": d.get("name", ""),
                "x": int(d.get("x", 0)), "y": int(d.get("y", 0)),
                "w": int(d.get("w", 0)), "h": int(d.get("h", 0)),
            }
        return {
            "gate_visible": bool(r.get("gateVisible")) and ok,
            "gate": _clean(r.get("gate")),
            "qr": _clean(r.get("qr")),
            "input": _clean(r.get("input")),
            "button": _clean(r.get("button")),
            "total": int(r.get("total", 0)),
            "text": r.get("reason", ""),
            "backend": "powershell",
            "raw": r,
        }

    # 原生
    win = _native.find_main_window(timeout=4)
    if not win:
        return {"gate_visible": False, "gate": None, "qr": None,
                "input": None, "button": None, "total": 0, "text": "",
                "backend": "native"}
    host = _native.find_render_host(win)
    if not host:
        return {"gate_visible": False, "gate": None, "qr": None,
                "input": None, "button": None, "total": 0, "text": "",
                "backend": "native"}
    snap = _native.snapshot(host)
    def _strip(d):
        if not d:
            return None
        return {k: d[k] for k in ("type", "name", "x", "y", "w", "h")}
    snap["gate"] = _strip(snap.get("gate"))
    snap["qr"] = _strip(snap.get("qr"))
    snap["input"] = _strip(snap.get("input"))
    snap["button"] = _strip(snap.get("button"))
    snap["gate_visible"] = bool(snap.get("gate_visible"))
    snap["total"] = len(snap.get("items") or [])
    snap["text"] = (snap.get("text") or "")[:2000]
    snap["backend"] = "native"
    return snap


# ------------------------------------------------------------------ 动作
def set_code(code: str) -> tuple[bool, str]:
    """把验证码写进输入框，返回 (成功, 实际值/原因)。"""
    if USE_PS:
        r = _ps.run("set", {"value": code, "hwnd": window_handle()})
        return bool(r.get("ok")), str(r.get("value") or r.get("reason") or "")
    # 原生
    win = _native.find_main_window(timeout=4)
    if not win:
        return False, "no window"
    host = _native.find_render_host(win)
    if not host:
        return False, "no host"
    snap = _native.snapshot(host)
    if not snap.get("input"):
        return False, "no input"
    ok = _native.set_edit_value(snap["input"], code)
    return ok, _native.read_edit_value(snap["input"])


def click_submit() -> tuple[bool, str]:
    if USE_PS:
        r = _ps.run("click", {"hwnd": window_handle()})
        return bool(r.get("ok")), str(r.get("how") or r.get("reason") or "")
    win = _native.find_main_window(timeout=4)
    if not win:
        return False, "no window"
    host = _native.find_render_host(win)
    if not host:
        return False, "no host"
    snap = _native.snapshot(host)
    if not snap.get("button"):
        return False, "no button"
    ok = _native.click_element(snap["button"])
    return ok, "invoke" if ok else "failed"


def reload_qr() -> bool:
    """点一下「重新加载二维码」，确保拿到的是新鲜二维码（旧的可能返回 410）。"""
    if USE_PS:
        r = _ps.run("reload", {"hwnd": window_handle()})
        return bool(r.get("ok"))
    win = _native.find_main_window(timeout=4)
    if not win:
        return False
    host = _native.find_render_host(win)
    if not host:
        return False
    snap = _native.snapshot(host)
    for it in snap.get("items") or []:
        if it["type"] == "ButtonControl" and "重新加载" in it["name"]:
            return _native.click_element(it)
    return False
