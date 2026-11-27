# -*- coding: utf-8 -*-
"""从 KeySteam 开屏弹窗里把二维码抠出来并解码。

取图方式（从稳到糙）：
    1. PrintWindow 抓窗口位图 —— 不受窗口遮挡/失焦影响，最可靠
    2. 屏幕截图兜底（需要窗口在最前）
定位方式：UI Automation 给出二维码元素的精确屏幕矩形，据此裁剪。

解码方式：OpenCV QRCodeDetector + 多轮增强（放大/二值化/反色）。
"""
from __future__ import annotations

import re
from typing import Optional

import cv2
import numpy as np

from . import screencap

# -------------------------------------------------------------------- 解码
def decode_img(img: Optional[np.ndarray]) -> Optional[str]:
    if img is None or img.size == 0:
        return None

    det = cv2.QRCodeDetector()

    def once(im) -> Optional[str]:
        try:
            data, _, _ = det.detectAndDecode(im)
            if data:
                return data
        except Exception:
            pass
        return None

    got = once(img)
    if got:
        return got

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    for scale in (2.0, 3.0, 4.0, 6.0):
        big = cv2.resize(gray, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_NEAREST)
        got = once(cv2.cvtColor(big, cv2.COLOR_GRAY2BGR))
        if got:
            return got

    for th in (100, 128, 150, 180):
        _, bw = cv2.threshold(gray, th, 255, cv2.THRESH_BINARY)
        got = once(cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR))
        if got:
            return got
        big = cv2.resize(bw, None, fx=3.0, fy=3.0,
                         interpolation=cv2.INTER_NEAREST)
        got = once(cv2.cvtColor(big, cv2.COLOR_GRAY2BGR))
        if got:
            return got

    inv = cv2.bitwise_not(img)
    got = once(inv)
    if got:
        return got
    inv_g = cv2.bitwise_not(gray)
    for scale in (1.0, 3.0):
        im = cv2.resize(inv_g, None, fx=scale, fy=scale,
                        interpolation=cv2.INTER_NEAREST)
        got = once(cv2.cvtColor(im, cv2.COLOR_GRAY2BGR))
        if got:
            return got

    return None


# ------------------------------------------------------------------ 高阶接口
def grab_qr_from_element(qr_el: dict, hwnd: int, log=print):
    """qr_el 是 uia.snapshot() 里的二维码条目；hwnd 是主窗口句柄。"""
    diag = {"tried": []}
    x, y, w, h = qr_el["x"], qr_el["y"], qr_el["w"], qr_el["h"]
    log(f"[二维码] 元素矩形 = ({x},{y}) {w}x{h}")

    # --- 1) PrintWindow（首选）---
    for pad in (8, 0, 20):
        sub = screencap.capture_region_of_window(
            hwnd, x - pad, y - pad, w + 2 * pad, h + 2 * pad)
        text = decode_img(sub)
        diag["tried"].append(f"PrintWindow(pad{pad}) -> {'OK' if text else 'fail'}")
        if text:
            diag["source"] = f"printwindow(pad{pad})"
            return text, diag

    # --- 2) 屏幕截图兜底（窗口需要在前）---
    try:
        from PIL import ImageGrab
        for pad in (8, 0, 20):
            img = ImageGrab.grab(bbox=(x - pad, y - pad,
                                       x + w + pad, y + h + pad),
                                 all_screens=True)
            arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            text = decode_img(arr)
            diag["tried"].append(f"screenGrab(pad{pad}) -> {'OK' if text else 'fail'}")
            if text:
                diag["source"] = f"screen(pad{pad})"
                return text, diag
    except Exception as e:
        diag["tried"].append(f"screenGrab 失败: {e}")

    # --- 3) 整个窗口位图里全图扫 ---
    full = screencap.capture_window(hwnd)
    text = decode_img(full)
    diag["tried"].append(f"PrintWindow(full) -> {'OK' if text else 'fail'}")
    if text:
        diag["source"] = "printwindow(full)"
        return text, diag

    return None, diag


_QUARK_RE = re.compile(
    r"https?://(?:pan\.quark\.cn|drive\.quark\.cn|pan\.uc\.cn)/s/[A-Za-z0-9]+[^\s\"']*",
    re.I,
)


def looks_like_quark(text: str) -> bool:
    return bool(_QUARK_RE.search(text or ""))
