# -*- coding: utf-8 -*-
"""KeySteam 验证码自动化 —— 主流程。

    KeySteam 开屏弹窗
        │  UI Automation 语义定位：WindowControl「KeySteam 验证」
        │                          ImageControl「验证码分享链接二维码」
        │                          EditControl「输入中间 6 位数字…」
        │                          ButtonControl「验证」
        ▼
    截二维码（PrintWindow，不受遮挡影响）→ OpenCV 解码
        ▼
    https://key.steamofl.com/q/<id>          （跳板页，需手机 UA）
        ▼  解 BigInt-LCG 工作量证明（无需真手机）
    https://pan.quark.cn/s/<share>
        ▼  匿名可读：stoken + 目录列表
    2026-11-27-0950/2026-11-27 验证码.zip      （约 760 B）
        ▼  需登录：转存 → 下载
    解压 → 取 6 位数字
        ▼
    写回输入框 → 点「验证」

命令：
    KeySteamAutoVerify.exe                 双击即用：没开就自动启动，开着就直接扫二维码
    KeySteamAutoVerify.exe --restart       先关掉再重新启动 KeySteam
    KeySteamAutoVerify.exe --no-launch     只接管已运行的实例，不自动启动
    KeySteamAutoVerify.exe --probe         只看界面结构
    KeySteamAutoVerify.exe --qr-only       只读二维码
    KeySteamAutoVerify.exe --resolve-only  解析到夸克链接
    KeySteamAutoVerify.exe --dry-run       拿码但不提交
    KeySteamAutoVerify.exe --manual        浏览器手动下载
    KeySteamAutoVerify.exe --code 123456   直接提交指定码
    KeySteamAutoVerify.exe --clean-drive   清掉网盘里遗留的旧验证码包

验证码文件约 20 分钟换一次、文件名却不变，所以取码策略是
「每次新建唯一临时目录转存 → 下载 → 立刻删除该目录」，
保证拿到的永远是刚转存的那份，而不是上一次的旧包（旧包必然提示失效）。
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time
import webbrowser

# Windows 控制台默认 GBK，强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src import (app, browser_login, browser_login_cdp, code_extract,
                 config, locate, qr, quark, resolver, ui, wizard)
else:
    from . import (app, browser_login, browser_login_cdp, code_extract,
               config, locate, qr, quark, resolver, ui, wizard)


LOG_FILE = None


def log(msg: str) -> None:
    line = time.strftime("[%H:%M:%S] ") + str(msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------ 下载监控
def watch_downloads(seconds: int, since: float):
    for cand in ("Downloads", "下载"):
        d = os.path.join(os.path.expanduser("~"), cand)
        if os.path.isdir(d):
            downloads = d
            break
    else:
        return None

    log(f"[监控] 盯着 {downloads}（最多 {seconds}s）")
    deadline = time.time() + seconds
    while time.time() < deadline:
        newest, newest_t = None, 0.0
        for pat in ("*.zip", "*.rar", "*.7z"):
            for p in glob.glob(os.path.join(downloads, pat)):
                t = os.path.getmtime(p)
                if t >= since - 5 and t > newest_t:
                    newest, newest_t = p, t
        if newest:
            s1 = os.path.getsize(newest)
            time.sleep(1.5)
            if s1 == os.path.getsize(newest) and s1 > 0:
                return newest
        time.sleep(1.5)
    return None


# ------------------------------------------------------------------ 主流程
def run(args) -> int:
    base = _base_dir()
    cfg_path = os.path.join(base, "config.json")
    cfg = config.load(cfg_path)
    config.save(cfg_path, cfg)

    exe = config.resolve(base, cfg["keysteam_exe"])
    cookies_path = config.resolve(base, cfg["cookies_file"])

    # ---- 只做"登录并导出 cookies" ----
    if getattr(args, "login", False):
        # 快路径：浏览器没在跑就直接读默认 profile
        got = browser_login_cdp.try_existing_profile()
        if got and browser_login_cdp.looks_logged_in(got):
            browser_login_cdp.save(cookies_path, got, log)
            log(f"[完成] 已从现有浏览器导出 {len(got)} 个 cookie")
            return 0
        # 主路径：独立 profile + CDP
        got = browser_login_cdp.login_and_capture(
            cookies_path, url=browser_login.QUARK_HOME,
            timeout=float(cfg.get("login_wait_seconds", 300)),
            keep_open=getattr(args, "keep_browser", False),
            log=log,
            preferred=cfg.get("browser_preference", "auto"))
        if got:
            log(f"[完成] cookies 已保存到 {cookies_path}")
            return 0
        log("[失败] 没有拿到 cookies")
        return 3

    # ---- 只做"清理网盘里的旧验证码残留" ----
    if getattr(args, "clean_drive", False):
        if not os.path.exists(cookies_path):
            log(f"[cookies] 找不到 {cookies_path}，先登录一次（--login）")
            return 3
        try:
            qc = quark.Quark(quark.load_cookies(cookies_path))
            n = qc.clear_legacy_code_files(log)
            base = cfg.get("quark_save_dir") or ""
            if base:
                qc._sweep_runs(base, None, log)
            log(f"[完成] 清理了 {n} 个旧验证码包")
            return 0
        except quark.QuarkError as e:
            log(f"[失败] 清理出错: {e}")
            return 4

    # ---- 定位安装位置：配置 → 运行中进程 → 注册表 → 常见目录 ----
    exe, how = locate.find(exe, log=log)
    if not exe:
        log(f"[错误] {locate.install_hint()}")
        return 2
    if how != "config" and cfg.get("keysteam_exe") != exe:
        cfg["keysteam_exe"] = exe
        config.save(cfg_path, cfg)
        log(f"[定位] 已写回配置: {exe}")
    log(f"[定位] KeySteam = {exe}（来源：{locate.describe(how)}）")

    # ---- 启动策略：开着就接管，没开就自动启动 ----
    if getattr(args, "restart", False) and app.is_running():
        app.kill_keysteam(log)
    try:
        hwnd = app.ensure_window(
            exe,
            timeout=float(cfg.get("launch_wait_seconds", 75)),
            auto_launch=not getattr(args, "no_launch", False)
            and bool(cfg.get("auto_launch", True)),
            log=log)
    except RuntimeError as e:
        log(f"[失败] {e}")
        return 8
    app.bring_to_front(hwnd)

    # ---- 探测 ----
    if args.probe:
        snap = ui.snapshot()
        log(f"[探测] 后端={snap.get('backend')} 控件数={snap.get('total')} "
            f"弹窗={snap.get('gate_visible')}")
        for key, label in (("gate", "弹窗"), ("qr", "二维码"),
                           ("input", "输入框"), ("button", "验证按钮")):
            it = snap.get(key)
            if it:
                log(f"[探测] {label}: {it['type']} name={it['name']!r} "
                    f"rect=({it['x']},{it['y']}) {it['w']}x{it['h']}")
            else:
                log(f"[探测] {label}: 未找到")
        return 0

    # ---- 状态 ----
    snap = app.wait_for_gate(6.0)
    log(f"[状态] 弹窗={snap.get('gate_visible')}")
    if not snap.get("gate_visible"):
        log("[完成] 没有验证弹窗 —— 票据仍有效，直接可用。")
        return 0

    if not snap.get("qr"):
        log("[失败] 找不到二维码元素（界面结构可能变了）")
        return 3

    # ---- 读二维码（先刷新，拿到新鲜的）----
    text = ""
    share_url = ""
    for attempt in (1, 2):
        if ui.reload_qr():
            log("[二维码] 已点击「重新加载二维码」")
            time.sleep(1.6)
        snap = ui.snapshot()
        if not snap.get("qr"):
            log("[失败] 找不到二维码元素")
            return 3
        text, diag = qr.grab_qr_from_element(snap["qr"], hwnd, log)
        if not text:
            log("[失败] 二维码解不出：")
            for line in diag.get("tried", []):
                log("   " + line)
            return 3
        log(f"[二维码] {text}")

        if args.qr_only:
            return 0

        try:
            share_url = resolver.resolve(text, log)
            break
        except resolver.ResolveError as e:
            log(f"[解析] 第 {attempt} 次失败: {e}")
            if attempt == 2 or args.code:
                if not args.code and not args.manual:
                    return 3
                break

    if not share_url and not args.code:
        log("[失败] 解析不到夸克链接")
        return 3

    if args.resolve_only:
        log(f"[解析] 夸克分享地址 = {share_url}")
        return 0

    # ---- 拿验证码 ----
    code = args.code

    if not code and share_url and not args.manual:
        # ---- 没有 cookies：先试静默导出，不行就引导浏览器登录 ----
        if not os.path.exists(cookies_path):
            log(f"[cookies] 没有 {os.path.basename(cookies_path)}")
            got = None
            if not getattr(args, "no_auto_cookie", False):
                log("[cookies] 先看现有浏览器里有没有登录态…")
                got = browser_login_cdp.try_existing_profile()
                if got and browser_login_cdp.looks_logged_in(got):
                    browser_login_cdp.save(cookies_path, got, log)
                    log(f"[cookies] 从现有浏览器导出 {len(got)} 个 cookie")
                else:
                    log("[cookies] 需要你在新窗口里登录一次夸克")
                    got = browser_login_cdp.login_and_capture(
                        cookies_path,
                        url=share_url or browser_login.QUARK_HOME,
                        timeout=float(cfg.get("login_wait_seconds", 240)),
                        keep_open=getattr(args, "keep_browser", False),
                        log=log,
                        preferred=cfg.get("browser_preference", "auto"))
            if not got:
                log("[cookies] 没拿到 cookies，改用浏览器手动下载模式")
                if cfg.get("open_browser_on_fail", True):
                    args.manual = True

        if os.path.exists(cookies_path):
            try:
                log(f"[夸克] 载入 cookies: {os.path.basename(cookies_path)}")
                cs = quark.load_cookies(cookies_path)
                log(f"[夸克] cookie 数 = {len(cs)}")
                for k in ("kps", "puus", "p_uid", "b-user-id", "sid"):
                    log(f"   {k}: {'有' if k in cs else '无'}")
                qc = quark.Quark(cs)
                fname, blob = qc.fetch_code_zip(
                    share_url, log,
                    base_folder=cfg.get("quark_save_dir") or "",
                    cleanup=bool(cfg.get("quark_cleanup", True)),
                    keep_copy=getattr(args, "keep_code", False))
                info = code_extract.extract_codes(fname, blob, log)
                code = code_extract.pick_code(info)
                log(f"[提取] 6位={info['six'][:5]} 完整={info['full'][:3]}")
                if not code:
                    log(f"[失败] 包里没找到 6 位码：{info}")
                    return 4
                log(f"[提取] 验证码 = {code}")
            except quark.QuarkError as e:
                log(f"[夸克] 自动流程失败: {e}")
                if cfg.get("open_browser_on_fail", True):
                    args.manual = True

    if not code and args.manual:
        since = time.time()
        target = share_url or text
        log(f"[浏览器] 打开: {target}")
        try:
            webbrowser.open(target)
        except Exception as e:
            log(f"[浏览器] 打开失败: {e}")
        fpath = watch_downloads(int(cfg["download_watch_seconds"]), since)
        if not fpath:
            log("[失败] 没等到下载文件")
            return 5
        log(f"[下载] {os.path.basename(fpath)}")
        with open(fpath, "rb") as f:
            blob = f.read()
        info = code_extract.extract_codes(os.path.basename(fpath), blob, log)
        code = code_extract.pick_code(info)
        if not code:
            log(f"[失败] 提取不到 6 位码: {info}")
            return 4
        log(f"[提取] 验证码 = {code}")

    if not code:
        log("[失败] 没有可用验证码")
        return 4

    if args.dry_run:
        log(f"[dry-run] 拿到验证码 {code}，不提交")
        return 0

    # ---- 提交 ----
    log(f"[提交] 写入 {code} …")
    res = app.fill_and_submit(hwnd, code, log)
    if res.get("ok"):
        log("[成功] 验证通过，弹窗已消失")
        return 0
    log(f"[失败] stage={res.get('stage')} detail={res.get('detail')}")
    return 6


def _selftest() -> int:
    import traceback
    log("== 自检 ==")
    log(f"frozen = {getattr(sys, 'frozen', False)}")
    log(f"backend = {'powershell' if ui.USE_PS else 'native'}")
    try:
        hwnd = ui.window_handle()
        log(f"KeySteam hwnd = {hwnd}")
    except Exception:
        log("窗口枚举失败:\n" + traceback.format_exc())
        return 1
    if not hwnd:
        log("KeySteam 未运行")
        return 1
    try:
        snap = ui.snapshot()
        log(f"控件数 = {snap.get('total')} 弹窗 = {snap.get('gate_visible')}")
        log(f"二维码 = {snap.get('qr')}")
        log(f"输入框 = {snap.get('input')}")
        log(f"按钮   = {snap.get('button')}")
        log(f"snap.raw = {str(snap.get('raw'))[:500]}")
        log(f"hwnd now = {ui.window_handle()}")
        try:
            from src import uia_ps as _ps
            raw = _ps.run("find")
            log(f"PS raw keys = {list(raw.keys())}")
            log(f"PS raw = {str(raw)[:400]}")
        except Exception:
            log("直接调 PS 失败:\n" + traceback.format_exc())
    except Exception:
        log("快照失败:\n" + traceback.format_exc())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="KeySteam 验证码自动化（二维码 → 夸克取码 → 自动提交）")
    ap.add_argument("--qr-only", action="store_true")
    ap.add_argument("--resolve-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--code", default="")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--restart", action="store_true", help="由本工具重启 KeySteam")
    ap.add_argument("--no-launch", action="store_true",
                    help="KeySteam 没开时不要自动启动，只接管已运行的实例")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--log", default="", help="把日志同时写到文件")
    ap.add_argument("--no-auto-cookie", action="store_true",
                    help="不从浏览器自动导出 cookie")
    ap.add_argument("--keep-browser", action="store_true",
                    help="登录用的浏览器窗口不自动关闭")
    ap.add_argument("--login", action="store_true",
                    help="只做浏览器登录并导出 cookies，不继续验证流程")
    ap.add_argument("--keep-code", action="store_true",
                    help="取完码后保留网盘里的临时目录（仅调试用）")
    ap.add_argument("--clean-drive", action="store_true",
                    help="只清理网盘里遗留的旧验证码包，然后退出")
    # 双击运行（没有任何命令行参数）-> 直接进交互向导，不需要用户敲命令
    if len(sys.argv) <= 1:
        try:
            return wizard.run_wizard()
        except KeyboardInterrupt:
            print("\n  已取消")
            return 130
        except Exception as e:
            import traceback
            print(f"\n  出错了：{type(e).__name__}: {e}")
            traceback.print_exc()
            try:
                input("\n  按回车键退出…")
            except Exception:
                pass
            return 9

    args = ap.parse_args()

    if args.log:
        global LOG_FILE
        LOG_FILE = args.log
        try:
            open(LOG_FILE, "w", encoding="utf-8").close()
        except Exception:
            LOG_FILE = None

    if args.selftest:
        return _selftest()

    try:
        return run(args)
    except KeyboardInterrupt:
        log("已取消")
        return 130
    except Exception as e:
        log(f"[异常] {type(e).__name__}: {e}")
        return 9


if __name__ == "__main__":
    sys.exit(main())
