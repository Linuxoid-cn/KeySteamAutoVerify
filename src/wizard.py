# -*- coding: utf-8 -*-
"""零参数交互向导 —— 双击直接跑这个。

完整流程（全程无需输入任何命令）：
    1. 检查 cookies.json；没有就自动开浏览器 → 等你登录 → 自动生成
    2. 找到 KeySteam 的验证弹窗
    3. 读二维码 → 解析夸克分享
    4. 下载验证码压缩包 → 提取 6 位码
    5. 自动填入并点「验证」
    6. 结果用自然语言告诉你，等你按回车再关窗
"""
from __future__ import annotations

import os
import sys
import time

from . import (app, browser_login_cdp, code_extract, config,
               console_ui as cui, qr, quark, resolver)
from . import ui as uiops


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


TOTAL_STEPS = 5


# --------------------------------------------------------------- 第 1 步：cookie
def ensure_cookies(cookies_path: str, share_url: str, cfg: dict) -> bool:
    cui.step(1, TOTAL_STEPS, "检查夸克登录状态")

    if os.path.exists(cookies_path):
        cui.ok(f"已有登录信息：{os.path.basename(cookies_path)}")
        return True

    cui.warn("还没登录过夸克，需要先登录一次（只需一次）")
    cui.info("")

    # 快路径：浏览器没在跑，直接读
    got = browser_login_cdp.try_existing_profile()
    if got and browser_login_cdp.looks_logged_in(got):
        browser_login_cdp.save(cookies_path, got, cui.info)
        cui.ok(f"已从浏览器读到登录信息，保存为 {os.path.basename(cookies_path)}")
        return True

    # 主路径：开独立窗口登录
    cui.info("正在打开浏览器窗口，请在窗口里登录夸克…")
    got = browser_login_cdp.login_and_capture(
        cookies_path,
        url=share_url or "https://pan.quark.cn/",
        timeout=float(cfg.get("login_wait_seconds", 300)),
        keep_open=False,
        log=lambda m: None,          # 向导自己打进度，屏蔽内部日志
        progress=_login_progress,
    )
    if got:
        cui.ok(f"登录成功，已保存 {os.path.basename(cookies_path)}（{len(got)} 项）")
        cui.info("下次运行就不用再登录了")
        return True

    cui.err("没有检测到登录状态")
    cui.info("如果你已经登录了，可能是浏览器没关干净，重跑一次即可")
    return False


_last = {"t": 0.0}


def _login_progress(remain: int, cookie_count: int) -> None:
    if remain % 2 and remain != 0:
        return
    extra = f"（已拿到 {cookie_count} 项）" if cookie_count else "（等待登录…）"
    cui.countdown_line("请在弹出的浏览器里登录夸克，", remain, extra)


# ------------------------------------------------------------- 第 2 步：找界面
def attach_ui() -> int | None:
    cui.step(2, TOTAL_STEPS, "寻找 KeySteam 验证窗口")

    if not app.is_running():
        cui.err("KeySteam 没有运行")
        cui.info("请先打开 KeySteam，等它弹出「KeySteam 验证」窗口后再运行本程序")
        return None

    try:
        hwnd = app.attach(timeout=25, log=lambda m: None)
    except Exception:
        cui.err("找不到 KeySteam 界面元素")
        cui.info("请确认「KeySteam 验证」弹窗是打开状态")
        return None

    app.bring_to_front(hwnd)
    snap = uiops.snapshot()

    if not snap.get("gate_visible"):
        cui.ok("没有验证弹窗 —— 你现在处于已解锁状态，不需要验证")
        return 0      # 特殊值：无需处理

    cui.ok("已找到验证弹窗")
    if snap.get("qr"):
        cui.info(f"二维码位置：{snap['qr']['w']}×{snap['qr']['h']}")
    return hwnd


# ----------------------------------------------------------- 第 3 步：取二维码
def get_share_url(hwnd: int) -> str:
    cui.step(3, TOTAL_STEPS, "读取弹窗里的二维码")

    last_err = ""
    for attempt in (1, 2, 3):
        if attempt > 1:
            cui.warn(f"重试第 {attempt} 次（二维码有时效，先刷新）")
        if uiops.reload_qr():
            time.sleep(1.8)

        snap = uiops.snapshot()
        if not snap.get("qr"):
            last_err = "找不到二维码元素"
            continue

        text, _diag = qr.grab_qr_from_element(snap["qr"], hwnd, lambda m: None)
        if not text:
            last_err = "二维码图片解不出来"
            continue
        cui.ok("二维码已识别")

        try:
            url = resolver.resolve(text, lambda m: None)
            cui.ok(f"网盘地址：{url}")
            return url
        except resolver.ResolveError as e:
            last_err = str(e)
            continue

    cui.err(f"读取二维码失败：{last_err}")
    return ""


# ----------------------------------------------------------- 第 4 步：拿验证码
def get_code(share_url: str, cookies_path: str, cfg: dict) -> str:
    cui.step(4, TOTAL_STEPS, "从网盘获取今天的验证码")

    cs = quark.load_cookies(cookies_path)
    qc = quark.Quark(cs)

    try:
        fname, blob = qc.fetch_code_zip(share_url, lambda m: None)
    except quark.QuarkError as e:
        msg = str(e)
        cui.err(f"下载失败：{msg}")
        if "过期" in msg or "登录" in msg or "31001" in msg:
            cui.info("登录信息可能失效了，正在重新拉取…")
            got = browser_login_cdp.login_and_capture(
                cookies_path, url="https://pan.quark.cn/",
                timeout=float(cfg.get("login_wait_seconds", 300)),
                keep_open=False, log=lambda m: None,
                progress=_login_progress)
            if got:
                qc = quark.Quark(got)
                fname, blob = qc.fetch_code_zip(share_url, lambda m: None)
            else:
                return ""
        else:
            return ""

    cui.ok(f"已下载：{fname}（{len(blob)} 字节）")
    info = code_extract.extract_codes(fname, blob, lambda m: None)
    code = code_extract.pick_code(info)
    if not code:
        cui.err(f"压缩包里没找到 6 位验证码，内容：{info.get('files')}")
        return ""
    cui.ok(f"验证码：{code}")
    return code


# ------------------------------------------------------------ 第 5 步：提交
def submit(hwnd: int, code: str) -> bool:
    cui.step(5, TOTAL_STEPS, "填入验证码并提交")
    app.bring_to_front(hwnd)
    res = app.fill_and_submit(hwnd, code, lambda m: None)

    if res.get("ok"):
        cui.ok("验证通过，弹窗已消失 —— 现在可以正常使用了")
        return True

    stage = res.get("stage")
    detail = res.get("detail")
    if stage == "rejected":
        cui.err("验证码被拒绝（可能是别人刚用掉了，稍等再试）")
        cui.info(f"服务器回复：{str(detail)[:120]}")
    elif stage == "timeout":
        cui.warn("已提交但没等到弹窗消失，请看一眼 KeySteam 窗口")
    else:
        cui.err(f"提交失败：{stage} / {str(detail)[:120]}")
    return False


# ------------------------------------------------------------------ 主入口
def run_wizard() -> int:
    base = _base_dir()
    cfg_path = os.path.join(base, "config.json")
    cfg = config.load(cfg_path)
    config.save(cfg_path, cfg)

    cookies_path = config.resolve(base, cfg["cookies_file"])

    cui.banner()

    # 先看 KeySteam 有没有开着（问题最常见）
    if not app.is_running():
        cui.warn("KeySteam 现在没在运行")
        cui.info("请先打开 KeySteam，等它弹出「KeySteam 验证」窗口")
        cui.press_enter()
        return 8

    # 第 2 步先跑，判断是否真的需要验证（省得白登录）
    hwnd = attach_ui()
    if hwnd is None:
        cui.press_enter()
        return 2
    if hwnd == 0:
        cui.press_enter()
        return 0

    share_url = get_share_url(hwnd)
    if not share_url:
        cui.press_enter()
        return 3

    # 现在才去准备 cookie（顺便把分享链接带进登录页，登录后直接能存）
    if not ensure_cookies(cookies_path, share_url, cfg):
        cui.press_enter()
        return 1

    code = get_code(share_url, cookies_path, cfg)
    if not code:
        cui.press_enter()
        return 4

    done = submit(hwnd, code)

    print()
    if done:
        print(f"  {cui.C_OK}全部完成{cui.C_END}")
    else:
        print(f"  {cui.C_WARN}没成功，可以把上面的提示截图给我{cui.C_END}")
    cui.press_enter()
    return 0 if done else 6


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(run_wizard())
