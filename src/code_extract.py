# -*- coding: utf-8 -*-
"""从下载到的压缩包里提取 6 位验证码。

弹窗原文：
    输入中间 6 位数字，也可粘贴完整验证码
    请一定不要在线解压！！！

所以压缩包里通常是一张图或一个文本，里面藏着完整验证码，
中间 6 位就是要输入的部分。这里把所有文本类内容都扫一遍。
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from typing import Optional

# 6 位纯数字（前后不能是数字，避免误截长串）
_SIX = re.compile(r"(?<!\d)(\d{6})(?!\d)")
# 完整验证码一般是 12~32 位字母数字混合
_FULL = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{12,64})(?![A-Za-z0-9])")

_TEXT_EXT = {".txt", ".md", ".json", ".ini", ".cfg", ".log", ".csv", ".xml", ".html", ".htm"}
_IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def _seven_zip() -> Optional[str]:
    for name in ("7z.exe", "7za.exe", "7zr.exe"):
        p = shutil.which(name)
        if p:
            return p
    for cand in (
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ):
        if os.path.exists(cand):
            return cand
    return None


def _unzip_to(data: bytes, workdir: str) -> list[str]:
    """把压缩包解开，返回解出来的文件路径列表。"""
    os.makedirs(workdir, exist_ok=True)
    out: list[str] = []

    # 先试 zip
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                # 防目录穿越
                name = os.path.basename(info.filename.replace("\\", "/"))
                if not name:
                    continue
                dst = os.path.join(workdir, name)
                with z.open(info) as src, open(dst, "wb") as fp:
                    shutil.copyfileobj(src, fp)
                out.append(dst)
        if out:
            return out
    except Exception:
        pass

    # rar / 7z 交给 7-Zip
    sz = _seven_zip()
    if sz:
        arc = os.path.join(workdir, "_archive")
        with open(arc, "wb") as f:
            f.write(data)
        subprocess.run([sz, "x", "-y", f"-o{workdir}", arc],
                       capture_output=True, timeout=120)
        for name in os.listdir(workdir):
            p = os.path.join(workdir, name)
            if os.path.isfile(p) and name != "_archive":
                out.append(p)
    return out


def _ocr_image(path: str) -> str:
    """可选 OCR。没装 pytesseract 就跳过。"""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
        return pytesseract.image_to_string(Image.open(path), lang="eng") or ""
    except Exception:
        return ""


def extract_codes(file_name: str, data: bytes, log=print) -> dict:
    """返回 {'six': [...], 'full': [...], 'files': [...]}"""
    result = {"six": [], "full": [], "files": [], "raw_texts": []}
    workdir = tempfile.mkdtemp(prefix="kscode_")
    try:
        files = _unzip_to(data, workdir)
        log(f"[解包] {file_name} -> {len(files)} 个文件")
        result["files"] = [os.path.basename(f) for f in files]

        texts: list[str] = []
        for path in files:
            ext = os.path.splitext(path)[1].lower()
            if ext in _TEXT_EXT or ext == "":
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        texts.append(f.read())
                except Exception:
                    pass
            elif ext in _IMG_EXT:
                txt = _ocr_image(path)
                if txt:
                    texts.append(txt)
                    log(f"[OCR] {os.path.basename(path)} 识别到 {len(txt)} 字符")

        for t in texts:
            result["raw_texts"].append(t[:500])
            for m in _SIX.finditer(t):
                v = m.group(1)
                if v not in result["six"]:
                    result["six"].append(v)
            for m in _FULL.finditer(t):
                v = m.group(1)
                # 排除纯时间戳样式的
                if v.isdigit() and len(v) in (10, 13):
                    continue
                if v not in result["full"]:
                    result["full"].append(v)

        # 文件名里可能直接带码
        for f in result["files"]:
            for m in _SIX.finditer(f):
                v = m.group(1)
                if v not in result["six"]:
                    result["six"].append(v)

        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def pick_code(info: dict) -> Optional[str]:
    """从提取结果里挑出最可能是"中间 6 位"的那个。"""
    six = info.get("six") or []
    if six:
        return six[0]
    # 没有独立 6 位，就取完整码的中间 6 位
    for full in info.get("full") or []:
        if len(full) >= 6:
            mid = (len(full) - 6) // 2
            cand = full[mid:mid + 6]
            if cand.isdigit():
                return cand
    return None
