# -*- coding: utf-8 -*-
"""解析二维码里的 KeySteam 短链，拿到真正的夸克网盘分享地址。

机制（逆向自 https://key.steamofl.com/q/<id> 的落地页）：

    1. 服务端只对"手机 UA"返 200，桌面 UA 直接 403
       —— 页面上写着"用手机扫个码吧"，就是这个意思
    2. 页面 JS 里藏着一个 BigInt 线性同余发生器（LCG）工作量证明：
           x = (x * a + c) mod m     重复 n 次
           answer = x.toString(16)
       其中 x/m/a/c/n 都由服务端每次随机下发
    3. 把 ticket + answer 以 JSON POST 到 /q/<id>/u
    4. 返回 {"ok":true,"url":"https://pan.quark.cn/s/xxxx"}   <-- 真正的分享地址

    所以这里完全用 Python 复刻，不需要真手机。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 直接就是夸克分享的情况
_QUARK_RE = re.compile(
    r"https?://(?:pan\.quark\.cn|drive\.quark\.cn|pan\.uc\.cn)/s/[A-Za-z0-9]+[^\s\"']*",
    re.I,
)
# KeySteam 自己的跳板
_SHORT_RE = re.compile(r"https?://key\.steamofl\.com/q/([0-9a-fA-F]+)")


class ResolveError(RuntimeError):
    pass


def is_quark_link(text: str) -> bool:
    return bool(_QUARK_RE.search(text or ""))


def find_quark_link(text: str) -> str:
    m = _QUARK_RE.search(text or "")
    return m.group(0) if m else ""


def resolve(qr_text: str, log=print, timeout: float = 25.0) -> str:
    """把二维码内容解析成夸克分享链接。已经是夸克链接就原样返回。"""
    text = (qr_text or "").strip()
    if not text:
        raise ResolveError("二维码内容为空")

    if is_quark_link(text):
        log("[解析] 二维码本身就是夸克链接")
        return find_quark_link(text)

    m = _SHORT_RE.search(text)
    if not m:
        raise ResolveError(f"看不懂的二维码内容: {text[:120]}")

    short_url = m.group(0)
    log(f"[解析] KeySteam 短链: {short_url}")

    s = requests.Session()
    s.headers.update({"User-Agent": MOBILE_UA, "Accept": "text/html,*/*"})

    r = s.get(short_url, timeout=timeout)
    if r.status_code == 403:
        raise ResolveError("跳板页返回 403（可能需要换成手机 UA，或链接已失效）")
    if r.status_code != 200:
        raise ResolveError(f"跳板页返回 HTTP {r.status_code}")

    html = r.text

    # --- 1) 还原 POST 路径（页面用字符码数组藏起来）---
    arr = re.search(r"var\s+_=\[([\d,\s]+)\]", html)
    if not arr:
        # 也许页面已经直接给了夸克链接
        q = find_quark_link(html)
        if q:
            log("[解析] 页面里直接含夸克链接")
            return q
        raise ResolveError("落地页结构变了：找不到跳转路径数组")
    path = "".join(chr(int(x)) for x in arr.group(1).replace(" ", "").split(",") if x != "")

    # --- 2) 抽 LCG 参数 ---
    pm = re.search(
        r"x=B\(\"(\d+)\"\)\s*,\s*m=B\(\"(\d+)\"\)\s*,\s*"
        r"a=B\(\"(\d+)\"\)\s*,\s*c=B\(\"(\d+)\"\)\s*,\s*n=(\d+)",
        html,
    )
    if not pm:
        raise ResolveError("落地页结构变了：找不到工作量证明参数")
    x0, mod, mul, inc, n = (int(pm.group(1)), int(pm.group(2)),
                            int(pm.group(3)), int(pm.group(4)),
                            int(pm.group(5)))
    log(f"[解析] 工作量证明：{n} 轮 BigInt 迭代")

    # --- 3) 抽 ticket ---
    tm = re.search(r'ticket\s*:\s*"([A-Za-z0-9+/=]+)"', html)
    if not tm:
        raise ResolveError("落地页结构变了：找不到 ticket")
    ticket = tm.group(1)

    # --- 4) 算答案 ---
    x = x0
    for _ in range(n):
        x = (x * mul + inc) % mod
    answer = format(x, "x")
    log(f"[解析] 答案 = {answer[:24]}…")

    # --- 5) 提交 ---
    host = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(short_url))
    post_url = host + path
    headers = {
        "Content-Type": "application/json",
        "Referer": short_url,
        "Origin": host,
    }
    pr = s.post(post_url, json={"ticket": ticket, "answer": answer},
                headers=headers, timeout=timeout)
    if pr.status_code != 200:
        raise ResolveError(f"提交校验失败：HTTP {pr.status_code}")
    try:
        data = pr.json()
    except Exception:
        raise ResolveError(f"提交校验返回非 JSON: {pr.text[:200]}")

    if not data.get("ok"):
        raise ResolveError(f"校验未通过: {data.get('message') or data}")

    url = data.get("url") or ""
    if not is_quark_link(url):
        raise ResolveError(f"返回的地址不是夸克分享: {url[:160]}")

    log(f"[解析] 夸克分享地址: {url}")
    return url
