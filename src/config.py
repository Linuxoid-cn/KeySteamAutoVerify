# -*- coding: utf-8 -*-
"""配置读写。"""
from __future__ import annotations

import json
import os

DEFAULT = {
    "keysteam_exe": r"%LOCALAPPDATA%\KeySteam\keysteam.exe",
    "cookies_file": "cookies.json",
    "debug_port": 9222,
    # 转存验证码用的根目录（每次运行在其下建唯一临时目录，用完即删）
    "quark_save_dir": "KeySteam验证码",
    # 取到码后自动删掉临时目录 / 旧残留；调试时可设 false 保留现场
    "quark_cleanup": True,
    "open_browser_on_fail": True,
    "download_watch_seconds": 180,
    "auto_close_keysteam": True,
    "login_wait_seconds": 180,
}


def load(path: str) -> dict:
    cfg = dict(DEFAULT)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                cfg.update(json.load(f) or {})
        except Exception:
            pass
    return cfg


def save(path: str, cfg: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def resolve(base_dir: str, p: str) -> str:
    """相对路径按程序所在目录解析；支持 %LOCALAPPDATA% 这类环境变量。"""
    if not p:
        return p
    p = os.path.expandvars(os.path.expanduser(p))
    return p if os.path.isabs(p) else os.path.join(base_dir, p)
