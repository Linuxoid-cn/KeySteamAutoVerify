# -*- coding: utf-8 -*-
"""从浏览器里把指定站点的 cookie 导出来（Chromium 系：Chrome / Edge）。

原理（Chromium 的 cookie 加密方式）：
    Local State -> os_crypt.encrypted_key
        去掉前缀 "DPAPI"（5 字节），剩余用 Windows DPAPI 解密
        得到 32 字节 AES-256 主密钥
    每条 cookie 的 encrypted_value:
        b"v10" + 12 字节 nonce + 密文（AES-256-GCM，无附加数据）
        明文 = 值本身（新版还要去掉前 32 字节 SHA256(host) 校验）

    DPAPI 是"以当前用户身份加密"，所以同一用户下能直接解，不需要额外密码。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import sqlite3
import tempfile
from ctypes import wintypes
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CookieExportError(RuntimeError):
    pass


# ------------------------------------------------------------------ DPAPI
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_unprotect(blob: bytes) -> bytes:
    bio = _DATA_BLOB(len(blob),
                     ctypes.cast(ctypes.create_string_buffer(blob),
                                 ctypes.POINTER(ctypes.c_char)))
    bout = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(bio), None, None, None, None, 0, ctypes.byref(bout)):
        raise CookieExportError("DPAPI 解密失败（不是当前 Windows 用户加密的？）")
    return ctypes.string_at(bout.pbData, bout.cbData)


# ------------------------------------------------------------ 浏览器定位
def browser_userdata() -> list[tuple[str, str, str]]:
    """返回 [(名字, User Data 目录, 可执行文件)]。"""
    local = os.environ.get("LOCALAPPDATA", "")
    out = []
    cands = [
        ("Chrome", os.path.join(local, r"Google\Chrome\User Data"),
         r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("Edge", os.path.join(local, r"Microsoft\Edge\User Data"),
         r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("Quark", os.path.join(local, r"Quark\User Data"), ""),
        ("UC", os.path.join(local, r"UCBrowser\User Data"), ""),
    ]
    for name, ud, exe in cands:
        if os.path.isdir(ud):
            out.append((name, ud, exe if os.path.exists(exe) else ""))
    # 顺带扫 Program Files 里的 quark
    for base in (r"C:\Program Files", r"C:\Program Files (x86)"):
        for sub in ("Quark", "QuarkBrowser"):
            p = os.path.join(base, sub)
            if os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        if f.lower() in ("quark.exe", "quarkbrowser.exe"):
                            out.append(("Quark", "", os.path.join(root, f)))
                            break
    return out


def profile_dirs(user_data: str) -> list[str]:
    profs = []
    if os.path.isdir(os.path.join(user_data, "Default")):
        profs.append(os.path.join(user_data, "Default"))
    for n in os.listdir(user_data) if os.path.isdir(user_data) else []:
        if n.startswith("Profile ") and os.path.isdir(os.path.join(user_data, n)):
            profs.append(os.path.join(user_data, n))
    return profs




def _copy_shared(src: str, dst: str) -> bool:
    """用 CreateFileW 的共享读方式把文件内容拷出来。"""
    GENERIC_READ = 0x80000000
    FILE_SHARE_ALL = 0x00000007        # READ | WRITE | DELETE
    OPEN_EXISTING = 3
    try:
        k32 = ctypes.windll.kernel32
        h = k32.CreateFileW(str(src), GENERIC_READ, FILE_SHARE_ALL,
                            None, OPEN_EXISTING, 0, None)
        if h in (0, -1, None):
            return False
        try:
            chunks = []
            buf = ctypes.create_string_buffer(1 << 20)
            read = wintypes.DWORD(0)
            while True:
                ok = k32.ReadFile(h, buf, len(buf), ctypes.byref(read), None)
                if not ok or read.value == 0:
                    break
                chunks.append(buf.raw[:read.value])
            data = b"".join(chunks)
            if not data:
                return False
            with open(dst, "wb") as f:
                f.write(data)
            return True
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


def _copy_vss(src: str, dst: str) -> bool:
    """用 VSS 卷影副本拷贝（浏览器彻底锁死时的兜底）。"""
    try:
        import subprocess
        # 建一个临时快照
        r = subprocess.run(
            ["wmic", "shadowcopy", "call", "create",
             "Volume=C:\\", "Context=ClientAccessible"],
            capture_output=True, text=True, timeout=40)
        if r.returncode != 0:
            return False
        import re
        m = re.search(r"ShadowID\s*=\s*\"([^\"]+)\";?\s*\n?.*?ShadowID", r.stdout, re.S) \
            if False else re.search(r'(\\\?\\GLOBALROOT\\Device\\HarddiskVolumeShadowCopy\d+)', r.stdout)
        if not m:
            # wmic 输出里通常只给卷路径，另取
            r2 = subprocess.run(["vssadmin", "list", "shadows"], capture_output=True, text=True, timeout=30)
            m2 = re.findall(r"(\\\?\\GLOBALROOT\\Device\\HarddiskVolumeShadowCopy\d+)", r2.stdout)
            if not m2:
                return False
            shadow = m2[-1]
        else:
            shadow = m.group(1)
        # src 形如 C:\Users\... -> 拼到影子里
        rel = src.replace("C:\\", "", 1).lstrip("\\")
        p = shadow + "\\" + rel
        try:
            shutil.copy2(p, dst)
            return True
        except Exception:
            return False
    except Exception:
        return False


def _cookie_db(profile: str) -> Optional[str]:
    for rel in (r"Network\Cookies", "Cookies"):
        p = os.path.join(profile, rel)
        if os.path.exists(p):
            return p
    return None


# ------------------------------------------------------------ 解密
def _master_key(user_data: str) -> Optional[bytes]:
    ls = os.path.join(user_data, "Local State")
    if not os.path.exists(ls):
        return None
    st = json.load(open(ls, encoding="utf-8"))
    enc = st.get("os_crypt", {}).get("encrypted_key")
    if not enc:
        return None
    raw = base64.b64decode(enc)
    if raw[:5] == b"DPAPI":
        raw = raw[5:]
    return _dpapi_unprotect(raw)


def _decrypt_value(enc: bytes, key: bytes, host: str) -> str:
    if not enc:
        return ""
    if enc[:3] in (b"v10", b"v11"):
        nonce, ct = enc[3:15], enc[15:]
        try:
            pt = AESGCM(key).decrypt(nonce, ct, None)
        except Exception:
            return ""
        # 新版 Chromium 在明文前加了 32 字节 SHA256(host_key)
        if len(pt) > 32:
            import hashlib
            expected = hashlib.sha256(host.encode("utf-8")).digest()
            if pt[:32] == expected:
                pt = pt[32:]
        try:
            return pt.decode("utf-8", "replace")
        except Exception:
            return ""
    # v20 之类：Windows 上通常是 DPAPI 直加密
    try:
        return _dpapi_unprotect(enc).decode("utf-8", "replace")
    except Exception:
        return ""


# ------------------------------------------------------------ 导出


def browser_running(name: str) -> bool:
    """该浏览器是否正在运行（决定要不要提示用户先关掉）。"""
    import subprocess
    exe_map = {
        "Chrome": "chrome.exe",
        "Edge": "msedge.exe",
        "Quark": "quark.exe",
        "UC": "ucbrowser.exe",
    }
    exe = exe_map.get(name)
    if not exe:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=10).stdout
        return exe.lower() in out.lower()
    except Exception:
        return False


def close_browser(name: str, log=print) -> bool:
    """温和关闭浏览器（用 CloseMainWindow，不强杀，避免丢数据）。"""
    import subprocess
    exe_map = {"Chrome": "chrome.exe", "Edge": "msedge.exe",
               "Quark": "quark.exe", "UC": "ucbrowser.exe"}
    exe = exe_map.get(name)
    if not exe:
        return False
    try:
        r = subprocess.run(["taskkill", "/IM", exe], capture_output=True,
                           text=True, timeout=20)
        ok = r.returncode == 0
        if ok:
            log(f"[浏览器] 已关闭 {name}，等待它释放 cookie 数据库…")
            import time
            time.sleep(2.5)
        return ok
    except Exception:
        return False


def export_cookies(user_data: str,
                   domains: tuple[str, ...] = ("quark.cn", "uc.cn"),
                   only_names: tuple[str, ...] = ()) -> dict:
    """从某个 User Data 目录导出指定域名的 cookie -> {name: value}。"""
    key = _master_key(user_data)
    if not key:
        raise CookieExportError("取不到浏览器主密钥（Local State 缺失或格式不支持）")

    result: dict[str, str] = {}
    errors: list[str] = []

    for prof in profile_dirs(user_data):
        db = _cookie_db(prof)
        if not db:
            continue
        # 浏览器可能在占用（Windows 独占锁），按强度依次尝试
        tmp = os.path.join(tempfile.gettempdir(),
                           "ksav_ck_%d.db" % abs(hash(db)))
        copied = False

        # 1) 普通复制
        try:
            shutil.copy2(db, tmp)
            copied = True
        except Exception:
            pass

        # 2) 共享读方式打开（FILE_SHARE_READ|WRITE|DELETE）
        if not copied:
            copied = _copy_shared(db, tmp)

        # 3) VSS 卷影副本（需要管理员，失败就算了）
        if not copied:
            copied = _copy_vss(db, tmp)

        if not copied:
            errors.append(
                f"{prof}: 无法读取（浏览器正独占 cookie 数据库）。"
                f"请先完全退出浏览器再试，或直接用 --login 让程序引导登录。")
            continue
        try:
            con = sqlite3.connect(tmp)
            like = " OR ".join("host_key LIKE ?" for _ in domains)
            params = ["%" + d for d in domains]
            rows = con.execute(
                f"SELECT host_key,name,encrypted_value,value FROM cookies WHERE {like}",
                params).fetchall()
            con.close()
        except Exception as e:
            errors.append(f"{prof}: {e}")
            continue
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

        for host, name, enc, plain in rows:
            if only_names and name not in only_names:
                continue
            val = plain or _decrypt_value(enc, key, host)
            if not val:
                continue
            # 同名 cookie 以先到的为准（通常是 Default 配置）
            result.setdefault(name, val)

    if not result and errors:
        raise CookieExportError("；".join(errors[:3]))
    return result


def export_from_any(domains: tuple[str, ...] = ("quark.cn", "uc.cn")) -> tuple[str, dict]:
    """在所有已知浏览器里找，返回 (浏览器名, cookies)。"""
    tried = []
    for name, ud, _exe in browser_userdata():
        if not ud:
            continue
        tried.append(name)
        try:
            c = export_cookies(ud, domains)
            if c:
                return name, c
        except Exception:
            continue
    raise CookieExportError(f"这些浏览器里都没找到夸克 cookie：{tried or '无可用浏览器'}")
