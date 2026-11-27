# -*- coding: utf-8 -*-
"""启动/接管 KeySteam，并完成填码与提交（后端由 ui 模块统一调度）。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from . import ui


# ------------------------------------------------------------------ 进程管理
def _iter_keysteam_pids() -> list[int]:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq keysteam.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower().startswith("keysteam"):
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def is_running() -> bool:
    """优先用窗口枚举判断（tasklist 在打包环境下有时拿不到输出）。"""
    try:
        if ui.window_handle():
            return True
    except Exception:
        pass
    return bool(_iter_keysteam_pids())


def kill_keysteam(log=print) -> None:
    pids = _iter_keysteam_pids()
    if not pids:
        # 兜底：按窗口进程干掉
        try:
            hwnd = ui.window_handle()
            if hwnd:
                from . import uia as _u
                pid = _u._window_pid(hwnd)
                if pid:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                   capture_output=True, timeout=15)
        except Exception:
            pass
        return
    log(f"[进程] 关闭已运行的 KeySteam: {pids}")
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=15)
    for _ in range(40):
        if not is_running():
            return
        time.sleep(0.3)
    log("[进程] 警告：仍有残留进程")


def _clean_env() -> dict:
    env = os.environ.copy()
    for k in ("_MEIPASS", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR",
              "_PYI_PARENT_PROCESS_LEVEL", "_PYI_SPLASH_IPC",
              "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        parts = env.get("PATH", "").split(os.pathsep)
        env["PATH"] = os.pathsep.join(
            [p for p in parts if p and os.path.normcase(p) != os.path.normcase(meipass)])
    return env


def launch(exe_path: str, log=print) -> subprocess.Popen:
    log(f"[启动] {exe_path}")
    return subprocess.Popen([exe_path],
                            cwd=os.path.dirname(exe_path) or None,
                            env=_clean_env(),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------ 连接
def attach(timeout: float = 45.0, log=print):
    """等 KeySteam 窗口 + 控件树可用。返回窗口句柄。"""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        hwnd = ui.window_handle()
        if hwnd:
            snap = ui.snapshot()
            if snap.get("total"):
                log(f"[界面] 已连接（{snap.get('backend')} 后端，"
                    f"{snap['total']} 个控件）")
                return hwnd
            last = "控件树为空"
        else:
            last = "窗口未出现"
        time.sleep(0.8)
    raise RuntimeError(f"等不到 KeySteam 界面（{last}）")


def bring_to_front(hwnd: int) -> None:
    """把 KeySteam 拉到最前。截图和点击都用得到。"""
    try:
        import ctypes
        u = ctypes.windll.user32
        u.ShowWindow(ctypes.c_void_p(int(hwnd)), 9)      # SW_RESTORE
        u.SetForegroundWindow(ctypes.c_void_p(int(hwnd)))
    except Exception:
        pass
    time.sleep(0.3)


# ------------------------------------------------------------------ 填码提交
_ERROR_WORDS = ("格式无效", "不能为空", "验证码错误", "请重新验证",
                "额度", "过期", "服务暂不可用", "无效")


def fill_and_submit(hwnd: int, code: str, log=print) -> dict:
    bring_to_front(hwnd)

    ok, info = ui.set_code(code)
    if not ok:
        return {"ok": False, "stage": "fill", "detail": info}
    log(f"[填码] 已写入 {code}（输入框回读: {info!r}）")
    time.sleep(0.4)

    ok, how = ui.click_submit()
    if not ok:
        return {"ok": False, "stage": "click", "detail": how}
    log(f"[提交] 已点击验证按钮（{how}）")

    deadline = time.time() + 30
    last = ""
    while time.time() < deadline:
        time.sleep(1.2)
        snap = ui.snapshot()
        last = snap.get("text", "") or ""
        if not snap.get("gate_visible"):
            return {"ok": True, "stage": "done", "detail": "验证弹窗已消失"}
        if any(w in last for w in _ERROR_WORDS):
            time.sleep(2)
            snap2 = ui.snapshot()
            if any(w in (snap2.get("text") or "") for w in _ERROR_WORDS):
                return {"ok": False, "stage": "rejected",
                        "detail": (snap2.get("text") or "")[:300]}
    return {"ok": False, "stage": "timeout", "detail": last[:300]}
