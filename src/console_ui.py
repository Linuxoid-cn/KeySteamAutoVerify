# -*- coding: utf-8 -*-
"""双击运行时的交互引导：没有 cookies 就自动开浏览器让用户登录，
登录成功自动生成 cookies.json，然后无缝继续。

设计原则（针对"双击运行"这个场景）：
    * 不要求用户输入任何命令
    * 所有提示都是自然语言 + 自动倒数，不需要按键
    * 用户唯一要做的动作：在弹出的浏览器窗口里扫码/登录
    * 任何一步失败都给出明确的一句话指引，而不是抛出 traceback
"""
from __future__ import annotations

import sys

if sys.platform == "win32":
    try:
        import ctypes
        # 双击运行时保留窗口，避免一闪而过
        ctypes.windll.kernel32.SetConsoleTitleW("KeySteam 验证码助手")
    except Exception:
        pass


C_OK = "\033[92m"
C_WARN = "\033[93m"
C_ERR = "\033[91m"
C_DIM = "\033[90m"
C_END = "\033[0m"
# 署名 / 网址用另一种颜色，双击运行时一眼能看到出处
C_TITLE = "\033[1;96m"      # 标题：亮青 + 加粗
C_URL = "\033[96m"          # 网址：青色
C_AUTHOR = "\033[95m"       # 作者：洋红


def _enable_ansi() -> None:
    """让 Windows 控制台支持颜色。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


_enable_ansi()


def banner() -> None:
    print()
    print(C_DIM + "=" * 58 + C_END)
    print(f"  {C_TITLE}KeySteam 验证码助手{C_END}")
    print(f"  {C_URL}https://github.com/Linuxoid-cn{C_END}"
          f"  ·  by {C_AUTHOR}Kernix{C_END}")
    print(C_DIM + "=" * 58 + C_END)


def info(msg: str) -> None:
    print(f"  {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"  {C_OK}✓{C_END} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  {C_WARN}!{C_END} {msg}", flush=True)


def err(msg: str) -> None:
    print(f"  {C_ERR}✗{C_END} {msg}", flush=True)


def step(n: int, total: int, msg: str) -> None:
    print()
    print(f"  {C_DIM}[{n}/{total}]{C_END} {msg}", flush=True)


def press_enter(msg: str = "按回车键退出…") -> None:
    """双击场景下让用户看清结果再关窗口。"""
    try:
        if sys.stdin and sys.stdin.isatty():
            input(f"\n  {msg}")
    except Exception:
        pass


_IS_TTY = None


def _is_tty() -> bool:
    global _IS_TTY
    if _IS_TTY is None:
        try:
            _IS_TTY = bool(sys.stdout and sys.stdout.isatty())
        except Exception:
            _IS_TTY = False
    return _IS_TTY


_last_bucket = {"v": -1}


def countdown_line(prefix: str, remain: int, extra: str = "") -> None:
    """显示倒计时。

    终端里用 \\r 覆盖同一行；被重定向/没有 tty 时每 20 秒打一行，避免刷屏。
    """
    if _is_tty():
        text = f"  {prefix} 剩余 {remain:3d}s {extra}"
        try:
            sys.stdout.write("\r" + text + "   ")
            sys.stdout.flush()
        except Exception:
            pass
        return

    bucket = remain // 20
    if bucket == _last_bucket["v"]:
        return
    _last_bucket["v"] = bucket
    print(f"  {prefix} 剩余 {remain:3d}s {extra}", flush=True)


def end_line() -> None:
    try:
        sys.stdout.write("\n")
        sys.stdout.flush()
    except Exception:
        pass
