# -*- coding: utf-8 -*-
"""截图工具：用 PrintWindow 直接抓窗口位图（不受遮挡影响）。

为什么不用普通屏幕截图：
    KeySteam 弹窗经常被其它窗口挡住，屏幕截图抓到的就是别人的画面。
    PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT) 让窗口自己渲染一份位图，
    即使窗口在后台、被遮挡、甚至部分移出屏幕，也能拿到真实内容。

注意：Win32 句柄是 64 位的，必须显式声明 restype/argtypes，
      否则 ctypes 默认按 32 位 int 处理，会抛 OverflowError。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

HDC = wintypes.HANDLE
HBITMAP = wintypes.HANDLE
HGDIOBJ = wintypes.HANDLE

PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
BI_RGB = 0

# ---- 句柄/返回值类型声明（关键，缺了就会 OverflowError） ----
user32.GetWindowDC.restype = HDC
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wintypes.HWND, HDC]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.PrintWindow.restype = wintypes.BOOL
user32.PrintWindow.argtypes = [wintypes.HWND, HDC, wintypes.UINT]

gdi32.CreateCompatibleDC.restype = HDC
gdi32.CreateCompatibleDC.argtypes = [HDC]
gdi32.CreateCompatibleBitmap.restype = HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = HGDIOBJ
gdi32.SelectObject.argtypes = [HDC, HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [HGDIOBJ]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [HDC]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = [HDC, HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3)]


def _hwnd(x) -> int:
    """把各种来源的句柄安全转成 int（防溢出/防 ctypes 对象）。"""
    try:
        v = int(x)
    except Exception:
        return 0
    return v & 0xFFFFFFFFFFFFFFFF


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(_hwnd(hwnd)), ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def capture_window(hwnd: int) -> Optional[np.ndarray]:
    """抓窗口位图，返回 BGR ndarray。"""
    hw = _hwnd(hwnd)
    if not hw:
        return None
    left, top, w, h = get_window_rect(hw)
    if w <= 0 or h <= 0:
        return None

    hdc_window = user32.GetWindowDC(wintypes.HWND(hw))
    if not hdc_window:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(HDC(hdc_window))
    if not hdc_mem:
        user32.ReleaseDC(wintypes.HWND(hw), HDC(hdc_window))
        return None
    hbmp = gdi32.CreateCompatibleBitmap(HDC(hdc_window), int(w), int(h))
    if not hbmp:
        gdi32.DeleteDC(HDC(hdc_mem))
        user32.ReleaseDC(wintypes.HWND(hw), HDC(hdc_window))
        return None

    old = gdi32.SelectObject(HDC(hdc_mem), HGDIOBJ(hbmp))
    ok = user32.PrintWindow(wintypes.HWND(hw), HDC(hdc_mem), PW_RENDERFULLCONTENT)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = int(w)
    bi.bmiHeader.biHeight = -int(h)      # 负数 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = BI_RGB

    buf = ctypes.create_string_buffer(int(w) * int(h) * 4)
    gdi32.GetDIBits(HDC(hdc_mem), HBITMAP(hbmp), 0, int(h), buf,
                    ctypes.byref(bi), DIB_RGB_COLORS)

    gdi32.SelectObject(HDC(hdc_mem), HGDIOBJ(old))
    gdi32.DeleteObject(HGDIOBJ(hbmp))
    gdi32.DeleteDC(HDC(hdc_mem))
    user32.ReleaseDC(wintypes.HWND(hw), HDC(hdc_window))

    if not ok:
        return None

    arr = np.frombuffer(buf.raw, dtype=np.uint8).reshape(int(h), int(w), 4)
    return arr[:, :, :3].copy()      # BGRA -> BGR


def crop(img: np.ndarray, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
    if img is None:
        return None
    H, W = img.shape[:2]
    x0 = max(0, int(x)); y0 = max(0, int(y))
    x1 = min(W, int(x) + int(w)); y1 = min(H, int(y) + int(h))
    if x1 <= x0 or y1 <= y0:
        return None
    return img[y0:y1, x0:x1].copy()


def capture_region_of_window(hwnd: int, screen_x: int, screen_y: int,
                             w: int, h: int) -> Optional[np.ndarray]:
    """给定屏幕坐标矩形，在窗口位图里裁出对应区域。"""
    win_left, win_top, _ww, _wh = get_window_rect(hwnd)
    img = capture_window(hwnd)
    if img is None:
        return None
    return crop(img, int(screen_x) - win_left, int(screen_y) - win_top, w, h)
