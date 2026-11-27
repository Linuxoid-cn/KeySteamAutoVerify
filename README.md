# KeySteam 验证码助手 · KeySteam Auto Verify

> 一个帮 KeySteam 自动完成开屏验证码流程的小工具。
> 读二维码 → 解跳板页工作量证明 → 进夸克网盘取码 → 自动填表提交。
>
> A small helper that automates the KeySteam startup verification flow:
> read the QR code → solve the landing-page proof-of-work → fetch the code from
> Quark Drive → fill the form and submit.

<p align="center">
  <b>作者 / Author</b>：
  <a href="https://github.com/Linuxoid-cn">Kernix</a>
  · <a href="https://github.com/Linuxoid-cn">github.com/Linuxoid-cn</a>
</p>

---

## 中文文档

### 这是什么

KeySteam 每次打开会弹一个「KeySteam 验证」窗口，要求你：

1. 用微信或夸克扫二维码
2. 打开夸克网盘、把压缩包保存到自己网盘
3. 下载、解压、读出里面的 6 位验证码
4. 填进输入框、点「验证」

这个过程每天都要重复。本项目把它全自动化，**双击一次即可**。

### 工作原理

| 环节 | 技术手段 | 说明 |
|---|---|---|
| 定位界面元素 | **Windows UI Automation** | 按语义找控件（`KeySteam 验证` 窗口 / `验证码分享链接二维码` 图片 / `输入中间 6 位数字` 输入框 / `验证` 按钮），**不依赖坐标或版本号**，程序小改也能命中 |
| 截取二维码 | **PrintWindow** | 直接让窗口自己渲染位图，被遮挡、失焦都能抓到 |
| 识别二维码 | OpenCV `QRCodeDetector` | 带多轮增强（放大 / 二值化 / 反色） |
| 解析跳板页 | 复刻页面 JS 的 **BigInt-LCG 工作量证明** | `key.steamofl.com/q/<id>` 对桌面 UA 返回 403，需手机 UA；页面内 `x=(x*a+c)%m` 迭代 n 次，答案 POST 回去才吐真实网盘地址 |
| 读取网盘 | 夸克 Web 端 `drive-pc` 接口 | 分享 token / 目录浏览**匿名可读**；转存和下载需要登录 |
| 获取登录态 | **独立浏览器 profile + CDP** | 浏览器运行时会独占 cookie 数据库（WinError 32），所以新开一个隔离 profile 并用 DevTools 协议直接取 cookie |
| 提取验证码 | zipfile / 7-Zip + 正则 + OCR | 从压缩包里扫出「中间 6 位数字」 |
| 提交 | ValuePattern + InvokePattern | 走和人工一致的路径 |

### 快速开始

**第一步**：打开 KeySteam，等它弹出「KeySteam 验证」窗口。

**第二步**：双击 `KeySteamAutoVerify.exe`。

之后它会自己走完：

```
==========================================================
  KeySteam 验证码助手
==========================================================

  [2/5] 寻找 KeySteam 验证窗口
  ✓ 已找到验证弹窗
  二维码位置：368×369

  [3/5] 读取弹窗里的二维码
  ✓ 二维码已识别
  ✓ 网盘地址：https://pan.quark.cn/s/xxxxxxxx

  [1/5] 检查夸克登录状态
  ! 还没登录过夸克，需要先登录一次（只需一次）

  正在打开浏览器窗口，请在窗口里登录夸克…
  ✓ 登录成功，已保存 cookies.json（31 项）
  下次运行就不用再登录了

  [4/5] 从网盘获取今天的验证码
  ✓ 已下载：2026-11-27 验证码.zip（759 字节）
  ✓ 验证码：xxxxxx

  [5/5] 填入验证码并提交
  ✓ 验证通过，弹窗已消失 —— 现在可以正常使用了

  按回车键退出…
```

**你唯一要做的动作**：第一次运行时，在弹出的浏览器窗口里扫码登录夸克。
登录成功那一刻，程序自动把 cookie 写成同目录的 `cookies.json`。

> ⚠️ `cookies.json` 里有你的夸克账号凭据，**不要上传、不要分享**。

### 命令行参数（可选）

| 参数 | 作用 |
|---|---|
| 无参数 | 交互向导（双击时走的就是这个） |
| `--probe` | 只看界面结构，排错用 |
| `--qr-only` | 只读二维码 |
| `--resolve-only` | 只解析到网盘链接 |
| `--dry-run` | 拿到验证码但不提交 |
| `--manual` | 浏览器手动下载模式 |
| `--code 123456` | 直接提交指定验证码 |
| `--login` | 只做浏览器登录并导出 cookies |
| `--keep-browser` | 登录窗口不自动关闭 |
| `--no-auto-cookie` | 不从浏览器自动导出 cookie |
| `--log 文件` | 日志同时写文件 |
| `--selftest` | 环境自检 |

### 从源码运行

```bash
# 依赖
pip install opencv-python-headless numpy requests websocket-client pillow \
            uiautomation comtypes cryptography pyinstaller

# 直接运行（无参数 = 向导）
python -m src.main

# 打包
python -m PyInstaller --onedir --console --name KeySteamAutoVerify ^
  --collect-all uiautomation --collect-all comtypes ^
  --hidden-import comtypes.gen.UIAutomationClient ^
  --hidden-import websocket --hidden-import cryptography ^
  src\main.py
```

也可以直接双击仓库里的 `build.bat`。

### 已知限制

- **只支持 Windows**（依赖 UIA、PrintWindow、DPAPI、AV 等）。
- 必须在**正常桌面会话**里运行。受限沙箱（作业对象）中，子进程可能拿不到完整 UIA 控件树。
- 二维码短链有效期约 **20 分钟**，过期返回 HTTP 410；程序会自动点「重新加载二维码」重试。
- 票据有效期是**一天**（KeySteam 官方在验证码文件里说明：二维码有效期 20 分钟，激活后验证有效期一天）。
- 夸克登录态会随浏览器策略过期，届时重跑一次向导即可自动续上。

### 免责声明

本项目仅用于**自动化重复的图形界面操作**，不修改 KeySteam 本体、不绕过任何服务端校验、
不破解加密票据。验证码仍需通过官方渠道合法获取。

使用者应自行遵守所在地区法律法规及 KeySteam 的使用条款。

---

## English Documentation

### What it is

Every time you open KeySteam, a verification window appears:

1. Scan a QR code with WeChat or Quark
2. Open Quark Drive and save the shared archive to your own drive
3. Download, extract, and read the 6-digit code
4. Paste it into the input box and click "验证" (Verify)

This repo automates the whole thing. **One double-click.**

### How it works

| Stage | Technique | Notes |
|---|---|---|
| Locate UI elements | **Windows UI Automation** | Semantic lookup (window `KeySteam 验证`, image `验证码分享链接二维码`, edit `输入中间 6 位数字`, button `验证`). **No coordinates, no version strings** — survives minor UI changes |
| Capture the QR | **PrintWindow** | The window renders itself into a bitmap; works even when occluded or unfocused |
| Decode the QR | OpenCV `QRCodeDetector` | Multiple enhancement passes (upscale / threshold / invert) |
| Resolve landing page | Reimplemented **BigInt-LCG proof-of-work** | `key.steamofl.com/q/<id>` returns 403 for desktop UAs; the page runs `x=(x*a+c)%m` n times and expects the hex answer posted back before revealing the real drive URL |
| Read the drive | Quark `drive-pc` web API | Share token and directory listing are **anonymous**; save-to-drive and download require login |
| Obtain login state | **Isolated browser profile + CDP** | Chromium locks the cookie DB while running (WinError 32), so a dedicated profile is launched with `--remote-debugging-port` and cookies are read via the DevTools protocol |
| Extract the code | zipfile / 7-Zip + regex + OCR | Scans the archive for the 6-digit code |
| Submit | ValuePattern + InvokePattern | Same path a human would take |

### Quick start

**Step 1** — Open KeySteam and wait for the "KeySteam 验证" window.

**Step 2** — Double-click `KeySteamAutoVerify.exe` and follow the prompts.

The only manual action ever required is the **first-time Quark login** in the
browser window the tool opens. The cookie is captured automatically as soon as
you finish logging in.

> ⚠️ `cookies.json` contains your Quark credentials. Never commit or share it.

### CLI options

Same table as above; every flag is optional. With no arguments the interactive
wizard runs.

### Build from source

```bash
pip install opencv-python-headless numpy requests websocket-client pillow \
            uiautomation comtypes cryptography pyinstaller
python -m src.main            # run
build.bat                     # package
```

### Limitations

- **Windows only.**
- Requires an interactive desktop session (restricted job objects may break UIA).
- The QR short link expires in ~20 minutes (HTTP 410); the tool refreshes it automatically.
- The resulting ticket is valid for **one day**.
- Quark sessions expire eventually — re-run the wizard to refresh.

### Disclaimer

This tool only automates **repetitive GUI interactions**. It does not patch
KeySteam, bypass server-side validation, or crack encrypted tickets. The
verification code must still be obtained legitimately through the official
channel.

Users are responsible for complying with local laws and KeySteam's terms of use.

---

## 更新日志 / Changelog

见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证 / License

[MIT License](LICENSE) © 2026 [Kernix](https://github.com/Linuxoid-cn)
