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

    # 把「我们自己」的目录从 PATH 里摘掉。
    # 否则被拉起的 KeySteam 可能从打包目录 _internal 里解析 VCRUNTIME140.dll：
    # 一是让 KeySteam 悄悄依赖我们的文件夹（删了就崩），
    # 二是运行时锁住这些 dll，导致本工具无法自我更新/覆盖。
    dirty = set()
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirty.add(os.path.normcase(os.path.abspath(meipass)))
    if getattr(sys, "frozen", False):
        dirty.add(os.path.normcase(os.path.dirname(os.path.abspath(sys.executable))))
        dirty.add(os.path.normcase(os.path.join(
            os.path.dirname(os.path.abspath(sys.executable)), "_internal")))
    else:
        dirty.add(os.path.normcase(os.path.dirname(os.path.abspath(__file__))))

    parts = env.get("PATH", "").split(os.pathsep)
    keep = []
    for p in parts:
        if not p:
            continue
        try:
            norm = os.path.normcase(os.path.abspath(p))
        except Exception:
            keep.append(p)
            continue
        if any(norm == d or norm.startswith(d + os.sep) for d in dirty):
            continue
        keep.append(p)
    env["PATH"] = os.pathsep.join(keep)
    return env


def launch(exe_path: str, log=print):
    """启动 KeySteam。

    注意：优先用 explorer 间接启动，而不是直接 Popen。
    实测（打包后的 onedir 版本）直接拉起时，KeySteam 会把
    ``VCRUNTIME140.dll`` 解析到我们自己的 ``_internal`` 目录里 ——
    后果有两个：KeySteam 悄悄依赖我们的文件夹（我们一删它就跑不起来），
    以及运行时锁住这些 dll，导致本工具无法覆盖更新。
    交给 explorer 当父进程后，DLL 解析回到 ``C:\\Windows\\System32``。
    """
    if sys.platform == "win32" and os.name == "nt":
        try:
            log(f"[启动] {exe_path}（经 explorer，避免依赖我们的 _internal）")
            subprocess.Popen(["explorer.exe", exe_path], close_fds=True,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            log(f"[启动] explorer 方式失败，改用直接执行: {e}")

    log(f"[启动] {exe_path}")
    return subprocess.Popen([exe_path],
                            cwd=os.path.dirname(exe_path) or None,
                            env=_clean_env(),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


# ------------------------------------------------------------ 没开就自动开
def ensure_window(exe_path: str = "", timeout: float = 75.0,
                  auto_launch: bool = True, log=print) -> int:
    """确保 KeySteam 在运行，并返回它的主窗口句柄。

    * 已经在运行 → 直接接管（不杀掉、不打扰当前状态，接着扫二维码）
    * 没有运行   → 自动 locate 到的 exe 启动它，等窗口出现后接管
    """
    if is_running():
        log("[进程] KeySteam 已在运行 —— 直接接管，开始扫二维码")
        return attach(timeout=min(timeout, 30.0), log=log)

    if not auto_launch:
        raise RuntimeError("KeySteam 没有运行（已用 --no-launch 禁止自动启动）")

    if not exe_path or not os.path.exists(exe_path):
        raise RuntimeError("找不到 KeySteam 的可执行文件，无法自动启动")

    log("[进程] KeySteam 没有运行 —— 自动启动")
    proc = launch(exe_path, log)

    # 直接执行时能拿到 Popen；explorer 方式返回 True，跳过探测
    if hasattr(proc, "poll"):
        for _ in range(6):
            time.sleep(0.5)
            if proc.poll() is not None:
                log(f"[进程] 启动器已退出（exit={proc.returncode}），继续等窗口…")
                break

    return attach(timeout=timeout, log=log)


# ------------------------------------------------------------------ 连接
def attach(timeout: float = 45.0, log=print):
    """等 KeySteam 窗口 + 控件树可用。返回窗口句柄。

    刚启动时窗口先出来、控件树还在加载（可能只有 1 个壳控件），
    所以要等到「能看到验证弹窗 / 二维码」或「控件数足够多」才算可用。
    """
    deadline = time.time() + timeout
    last = ""
    seen_hwnd = 0
    best_total = 0
    while time.time() < deadline:
        hwnd = ui.window_handle()
        if not hwnd:
            last = "窗口未出现"
            time.sleep(0.8)
            continue
        seen_hwnd = hwnd
        snap = ui.snapshot()
        total = int(snap.get("total") or 0)
        best_total = max(best_total, total)
        if snap.get("gate_visible") or snap.get("qr") or total >= 20:
            log(f"[界面] 已连接（{snap.get('backend')} 后端，{total} 个控件）")
            return hwnd
        last = f"控件树还在加载（{total} 个控件）"
        time.sleep(0.8)

    if seen_hwnd and best_total:
        log(f"[界面] 等待超时，但已拿到窗口（最多 {best_total} 个控件），继续尝试")
        return seen_hwnd
    raise RuntimeError(f"等不到 KeySteam 界面（{last}）")


def wait_for_gate(timeout: float = 6.0) -> dict:
    """等验证弹窗出现 —— 程序刚启动时界面可能还没画完。

    返回最后一次快照（调用方看 gate_visible / qr 即可）。
    """
    deadline = time.time() + timeout
    snap = ui.snapshot()
    while not snap.get("gate_visible") and time.time() < deadline:
        time.sleep(0.8)
        snap = ui.snapshot()
    return snap


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
