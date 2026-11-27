# -*- coding: utf-8 -*-
"""夸克网盘（Quark Cloud Drive）客户端。

实测结论（2026-11 验证）：
    * 分享链接的 token / 目录浏览：**不需要登录**，匿名就能读
    * 转存(save) / 下载(download)：**需要登录**，否则 401 require login
    所以 cookies.json 只用在这两步。

KeySteam 的分享结构（实测）：
    /s/xxxx
      └── 2026-11-27-0950/            <- 以日期时间命名的目录
            ├── 你们的支持是四季坚持下来的最大动力！...
            ├── KeySteam永久免费，如果是付费获得的本软件...
            ├── KeySteam_3.3.2_x64-setup.exe
            └── 2026-11-27 验证码.zip   <- 要的就是这个（约 759 B）
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

import requests

BASE = "https://drive-pc.quark.cn/1/clouddrive"
COMMON = {"pr": "ucpro", "fr": "pc"}

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class QuarkError(RuntimeError):
    pass


# ----------------------------------------------------------------- 链接解析
def parse_share_url(url: str) -> tuple[str, str]:
    m = re.search(r"/(?:s|web/share)/([A-Za-z0-9]+)", url)
    if not m:
        raise QuarkError(f"看不懂的分享链接: {url}")
    pwd_id = m.group(1)
    m2 = re.search(r"[?&]pwd=([A-Za-z0-9]{1,8})", url)
    return pwd_id, (m2.group(1) if m2 else "")


# ------------------------------------------------------------------- cookies
def _normalize_cookies(raw: Any) -> dict:
    if isinstance(raw, str):
        out = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    if isinstance(raw, dict):
        if isinstance(raw.get("cookies"), (list, dict)):
            return _normalize_cookies(raw["cookies"])
        out = {}
        for k, v in raw.items():
            if isinstance(v, (str, int, float)):
                out[str(k)] = str(v)
            elif isinstance(v, dict) and "value" in v:
                out[str(k)] = str(v["value"])
        return out

    if isinstance(raw, list):
        out = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name")
            value = item.get("value") or item.get("Value")
            if name is None:
                continue
            dom = str(item.get("domain") or item.get("Domain") or "")
            if dom and not any(x in dom for x in ("quark", "uc.cn", "ucweb")):
                continue
            out[str(name)] = str(value if value is not None else "")
        return out

    raise QuarkError(f"无法识别的 cookies 格式: {type(raw)}")


def load_cookies(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        raw = json.load(f)
    c = _normalize_cookies(raw)
    if not c:
        raise QuarkError(f"{path} 里没读到任何 cookie")
    # 夸克的登录态实际是双下划线命名（__kps / __puus / __uid）
    has_core = any(c.get(k) for k in ("__kps", "__puus", "__uid", "kps", "puus"))
    if not has_core:
        raise QuarkError(
            "cookies.json 里没有夸克登录凭据（需要 __kps / __puus 这类）。"
            "请重新运行程序让它自动导出，或在浏览器登录夸克后重新导出。")
    return c


# --------------------------------------------------------------------- 客户端
class Quark:
    def __init__(self, cookies: Optional[dict] = None, timeout: float = 30.0):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": DEFAULT_UA,
            "Referer": "https://pan.quark.cn/",
            "Origin": "https://pan.quark.cn",
            "Accept": "application/json, text/plain, */*",
        })
        self.logged_in = bool(cookies)
        for k, v in (cookies or {}).items():
            self.s.cookies.set(k, v, domain=".quark.cn")
            self.s.cookies.set(k, v, domain=".uc.cn")
        self.timeout = timeout

    # ---------- 底层 ----------
    def _req(self, method: str, path: str, *, params: Optional[dict] = None,
             body: Optional[dict] = None) -> dict:
        url = f"{BASE}{path}"
        q = dict(COMMON)
        if params:
            q.update(params)
        try:
            if method.upper() == "GET":
                r = self.s.get(url, params=q, timeout=self.timeout)
            else:
                r = self.s.post(url, params=q, json=body or {},
                                timeout=self.timeout)
        except requests.RequestException as e:
            raise QuarkError(f"网络请求失败: {e}") from e

        txt = r.text or ""
        if "acw_sc__v2" in txt or txt.lstrip().startswith("<"):
            raise QuarkError("夸克返回了风控挑战页（acw_sc__v2）。"
                             "cookies 可能已过期，请在浏览器重新登录后重新导出。")
        try:
            data = r.json()
        except Exception:
            raise QuarkError(f"响应不是 JSON（HTTP {r.status_code}）: {txt[:200]}")

        code = data.get("code")
        if code not in (0, 200, None):
            msg = data.get("message") or data.get("msg") or str(data)
            if code == 31001:
                raise QuarkError("需要登录（31001 require login）。"
                                 "请提供有效的 cookies.json。")
            raise QuarkError(f"夸克接口错误 code={code}: {msg}")
        return data

    # ---------- 分享（匿名可用）----------
    def share_token(self, pwd_id: str, passcode: str = "") -> str:
        d = self._req("POST", "/share/sharepage/token",
                      body={"pwd_id": pwd_id, "passcode": passcode})
        st = (d.get("data") or {}).get("stoken")
        if not st:
            raise QuarkError(f"取 stoken 失败: {d}")
        return st

    def share_detail(self, pwd_id: str, stoken: str,
                     pdir_fid: str = "0") -> list[dict]:
        d = self._req("GET", "/share/sharepage/detail", params={
            "pwd_id": pwd_id, "stoken": stoken, "pdir_fid": pdir_fid,
            "force": 0, "_page": 1, "_size": 100,
            "_fetch_banner": 0, "_fetch_share": 1, "_fetch_total": 1,
            "_sort": "file_type:asc,updated_at:desc",
        })
        return ((d.get("data") or {}).get("list")) or []

    # ---------- 转存（需登录）----------
    def save_share(self, pwd_id: str, stoken: str, fid: str, fid_token: str,
                   to_pdir_fid: str = "0") -> str:
        d = self._req("POST", "/share/sharepage/save",
                      params={"stoken": stoken},
                      body={
                          "fid_list": [fid],
                          "fid_token_list": [fid_token],
                          "to_pdir_fid": to_pdir_fid,
                          "pwd_id": pwd_id,
                          "stoken": stoken,
                          "pdir_fid": "0",
                          "scene": "link",
                      })
        tid = (d.get("data") or {}).get("task_id")
        if not tid:
            raise QuarkError(f"转存失败: {d}")
        return tid

    def wait_task(self, task_id: str, timeout: float = 120.0,
                  interval: float = 1.2) -> dict:
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            d = self._req("GET", "/task", params={"task_id": task_id,
                                                  "retry_index": 0})
            last = d.get("data") or {}
            st = last.get("status")
            if st == 2:
                return last
            if st == 3:
                raise QuarkError(f"任务失败: {last}")
            time.sleep(interval)
        raise QuarkError(f"任务超时 {timeout}s: {last}")

    # ---------- 自己的文件（需登录）----------
    def list_dir(self, pdir_fid: str = "0") -> list[dict]:
        d = self._req("GET", "/file/sort", params={
            "pdir_fid": pdir_fid, "_page": 1, "_size": 200,
            "_fetch_total": 1, "_sort": "file_type:asc,updated_at:desc",
        })
        return ((d.get("data") or {}).get("list")) or []

    def download_urls(self, fids: list[str]) -> list[dict]:
        d = self._req("POST", "/file/download", body={"fids": fids})
        return d.get("data") or []

    # ---------- 高层：找到验证码 zip ----------
    @staticmethod
    def _pick_code_zip(items: list[dict]) -> Optional[dict]:
        zips = [it for it in items
                if not it.get("dir")
                and it.get("file_name", "").lower().endswith((".zip", ".rar", ".7z"))]
        if not zips:
            return None
        # 优先文件名里带"验证码"的
        for z in zips:
            if "验证码" in z.get("file_name", ""):
                return z
        return zips[0]

    def find_code_zip(self, share_url: str, log=print) -> dict:
        """在分享里定位到验证码压缩包，返回 {fid, token, name, pwd_id, stoken}。"""
        pwd_id, passcode = parse_share_url(share_url)
        log(f"[夸克] 分享 {pwd_id}（psw={passcode or '无'}）")
        stoken = self.share_token(pwd_id, passcode)
        log("[夸克] stoken 已获取（此步无需登录）")

        root = self.share_detail(pwd_id, stoken, "0")
        log(f"[夸克] 根目录 {len(root)} 项")
        for it in root:
            log(f"   - {it.get('file_name')} ({'目录' if it.get('dir') else '文件'})")

        # 直接命中
        hit = self._pick_code_zip(root)
        if hit:
            return self._pack(hit, pwd_id, stoken)

        # 进子目录找（通常是日期目录）
        for it in root:
            if not it.get("dir"):
                continue
            sub = self.share_detail(pwd_id, stoken, it["fid"])
            log(f"[夸克] 进入目录 {it.get('file_name')}：{len(sub)} 项")
            for x in sub:
                log(f"   - {x.get('file_name')} "
                    f"({'目录' if x.get('dir') else str(x.get('size')) + ' B'})")
            hit = self._pick_code_zip(sub)
            if hit:
                return self._pack(hit, pwd_id, stoken)

        raise QuarkError("分享里找不到验证码压缩包（.zip/.rar/.7z）")

    @staticmethod
    def _pack(item: dict, pwd_id: str, stoken: str) -> dict:
        return {
            "fid": item["fid"],
            "token": item.get("share_fid_token", ""),
            "name": item.get("file_name", ""),
            "size": item.get("size", 0),
            "pwd_id": pwd_id,
            "stoken": stoken,
        }

    def fetch_code_zip(self, share_url: str, log=print) -> tuple[str, bytes]:
        """转存 + 下载验证码压缩包，返回 (文件名, 字节)。"""
        if not self.logged_in:
            raise QuarkError("下载验证码需要登录夸克，请提供 cookies.json")

        info = self.find_code_zip(share_url, log)
        log(f"[夸克] 目标: {info['name']} ({info['size']} B)")

        # 转存到根目录
        tid = self.save_share(info["pwd_id"], info["stoken"],
                              info["fid"], info["token"], to_pdir_fid="0")
        log(f"[夸克] 转存任务 {tid}，等待…")
        self.wait_task(tid)
        log("[夸克] 转存完成")

        # 在根目录找它
        target = None
        for _ in range(10):
            files = self.list_dir("0")
            for f in files:
                if f.get("file_name") == info["name"]:
                    target = f
                    break
            if target:
                break
            time.sleep(1.0)
        if not target:
            raise QuarkError("转存后在自己网盘里找不到该文件")

        urls = self.download_urls([target["fid"]])
        if not urls:
            raise QuarkError("拿不到下载直链")
        url = urls[0].get("download_url")
        if not url:
            raise QuarkError(f"下载直链为空: {urls[0]}")

        log("[夸克] 开始下载…")
        r = self.s.get(url, timeout=180)
        r.raise_for_status()
        log(f"[夸克] 下载完成 {len(r.content)} B")
        return info["name"], r.content
