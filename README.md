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

<p align="center">
  <a href="https://github.com/Linuxoid-cn/KeySteamAutoVerify/releases/latest">
    <img src="https://img.shields.io/github/v/release/Linuxoid-cn/KeySteamAutoVerify?label=release&color=2ea043" alt="latest release">
  </a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="license"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20x64-0078d4" alt="platform">
</p>

## 下载 / Download

**[⬇️ 下载最新版](https://github.com/Linuxoid-cn/KeySteamAutoVerify/releases/latest)**
（当前 `v1.0.3`，Windows x64，约 80 MB）

解压后**双击 `KeySteamAutoVerify.exe` 即可**，KeySteam 没打开也会自动帮你启动。

- 不想用打包版：见下文「从源码运行」
- 每个版本的改动：见 [CHANGELOG.md](CHANGELOG.md) 与 [Releases](https://github.com/Linuxoid-cn/KeySteamAutoVerify/releases)

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
| 定位安装位置 | **注册表 / 运行中进程 / 常见目录** | 依次查 `config.json` → 正在运行的 `keysteam.exe` 镜像路径 → 注册表卸载项的 `DisplayIcon`/`InstallLocation`（`HKCU`、`HKLM`、`WOW6432Node` 都扫）→ `App Paths` → `%LOCALAPPDATA%\KeySteam` 等常见目录 → `PATH`。**换台机器、换安装盘都不用改配置**，找到后自动写回 `config.json` |
| 启动软件 | **开着就接管，没开就自动拉起** | 已运行时直接连上现有窗口（不重启、不动你的状态）；没运行时用上面定位到的 exe 自动启动，等控件树就绪后再继续扫二维码 |
| 定位界面元素 | **Windows UI Automation** | 按语义找控件（`KeySteam 验证` 窗口 / `验证码分享链接二维码` 图片 / `输入中间 6 位数字` 输入框 / `验证` 按钮），**不依赖坐标或版本号**，程序小改也能命中 |
| 截取二维码 | **PrintWindow** | 直接让窗口自己渲染位图，被遮挡、失焦都能抓到 |
| 识别二维码 | OpenCV `QRCodeDetector` | 带多轮增强（放大 / 二值化 / 反色） |
| 解析跳板页 | 复刻页面 JS 的 **BigInt-LCG 工作量证明** | `key.steamofl.com/q/<id>` 对桌面 UA 返回 403，需手机 UA；页面内 `x=(x*a+c)%m` 迭代 n 次，答案 POST 回去才吐真实网盘地址 |
| 读取网盘 | 夸克 Web 端 `drive-pc` 接口 | 分享 token / 目录浏览**匿名可读**；转存和下载需要登录 |
| 转存取码 | **每次新建唯一临时目录 → 下载 → 立刻删除** | 验证码包约 20 分钟换一次、文件名不变，所以每次转存都进 `KeySteam验证码/run-<时间>-<随机>/`，下完就删，绝不复用上一次的旧包 |
| 获取登录态 | **独立浏览器 profile + CDP** | 浏览器运行时会独占 cookie 数据库（WinError 32），所以新开一个隔离 profile 并用 DevTools 协议直接取 cookie |
| 提取验证码 | zipfile / 7-Zip + 正则 + OCR | 从压缩包里扫出「中间 6 位数字」 |
| 提交 | ValuePattern + InvokePattern | 走和人工一致的路径 |

### 快速开始

**只有一个动作**：双击 `KeySteamAutoVerify.exe`。

- KeySteam **没打开** → 自动从注册表找到安装位置、替你启动它，等界面就绪后接着扫二维码
- KeySteam **已经打开** → 直接接管，马上扫二维码，不重启、不打断你

之后它会自己走完：

```
==========================================================
  KeySteam 验证码助手
  https://github.com/Linuxoid-cn  ·  by Kernix
==========================================================
  KeySteam 位置：C:\...\KeySteam\keysteam.exe
  （来源：注册表）

  [1/5] 启动 / 接管 KeySteam
  KeySteam 没有运行 —— 正在自动启动…
  ✓ 已找到验证弹窗，准备扫描二维码
  二维码位置：368×369

  [2/5] 读取弹窗里的二维码
  ✓ 二维码已识别
  ✓ 网盘地址：https://pan.quark.cn/s/xxxxxxxx

  [3/5] 检查夸克登录状态
  ! 还没登录过夸克，需要先登录一次（只需一次）

  正在打开浏览器窗口，请在窗口里登录夸克…
  ✓ 登录成功，已保存 cookies.json（31 项）
  下次运行就不用再登录了

  [4/5] 从网盘获取今天的验证码
  ✓ 转存到临时目录 KeySteam验证码/run-20261127-1523-ab12cd
  ✓ 已下载：2026-11-27 验证码.zip（759 字节）
  ✓ 临时目录已删除，网盘里不会留旧码
  ✓ 验证码：xxxxxx

  [5/5] 填入验证码并提交
  ✓ 验证通过，弹窗已消失 —— 现在可以正常使用了

  按回车键退出…
```

标题是亮青色，**网址青色、作者名洋红**，双击运行时一眼能看到出处。

**你唯一要做的动作**：第一次运行时，在弹出的浏览器窗口里扫码登录夸克。
登录成功那一刻，程序自动把 cookie 写成同目录的 `cookies.json`。

> ⚠️ `cookies.json` 里有你的夸克账号凭据，**不要上传、不要分享**。

### 用哪个浏览器登录？

第一次登录取 cookie 时会开一个浏览器窗口，选哪个由 `config.json` 的 `browser_preference` 决定：

| 值 | 行为 |
|---|---|
| `auto`（默认） | **优先系统默认浏览器**（Edge / Chrome / Brave / 夸克浏览器都行）；若默认浏览器不是 Chromium 系（如 Firefox），自动回退 Chrome → Edge |
| `chrome` / `edge` | 指定那一款优先 |
| `C:\...\xxx.exe` | 直接用这个具体路径 |

两个要点：

- 登录用的是**独立 profile**（`%TEMP%\ksav\profile`），不读也不动你日常浏览器的数据，登录后窗口自动关闭。
- 只有 `--manual`（浏览器手动下载验证码）这一条路径是用**系统默认浏览器**打开分享页的。

### 为什么每次都要「新建目录 → 下载 → 删除」

验证码压缩包的内容大约 **20 分钟**刷新一次，但**文件名不变**（永远是 `2026-11-27 验证码.zip` 这种）。
旧版是直接把包转存到自己网盘根目录，于是第二次运行会这样翻车：

1. 第一次运行 → 根目录出现 `2026-11-27 验证码.zip`（好码）
2. 20 分钟后官方换了内容，你又运行一次 → 转存撞上**同名旧文件**，
   网盘里躺着的那份旧包还在，下载回来的仍是 20 分钟前的旧码
3. 把这个旧码提交上去 → KeySteam 提示「验证码失效」，程序失败

现在的流程：

| 步骤 | 行为 |
|---|---|
| 1 | 在 `KeySteam验证码/` 下建**唯一目录** `run-<时间戳>-<6位随机>`（并发、连续运行都撞不上） |
| 2 | 只把这次的包转进这个新目录 —— 目录是空的，不可能命中历史文件 |
| 3 | 下载 → 解压 → 提取 6 位码 |
| 4 | `finally` 里删掉整个临时目录（成功失败都删），网盘回到干净状态 |
| 5 | 顺手清掉根目录里遗留的 `*验证码*.zip/.rar/.7z`，以及上次崩溃留下的 `run-*` 目录 |

跑完网盘里只会剩一个空的 `KeySteam验证码` 文件夹。
想留现场调试就加 `--keep-code`；想手动清一次历史残留跑 `--clean-drive`。

### 命令行参数（可选）

| 参数 | 作用 |
|---|---|
| 无参数 | 交互向导（双击时走的就是这个）：没开就自动启动，开着就直接扫二维码 |
| `--probe` | 只看界面结构，排错用 |
| `--restart` | 先关掉再重新启动 KeySteam |
| `--no-launch` | 没开也不要自动启动，只接管已运行的实例 |
| `--qr-only` | 只读二维码 |
| `--resolve-only` | 只解析到网盘链接 |
| `--dry-run` | 拿到验证码但不提交 |
| `--manual` | 浏览器手动下载模式 |
| `--code 123456` | 直接提交指定验证码 |
| `--login` | 只做浏览器登录并导出 cookies |
| `--clean-drive` | 只清理网盘里遗留的旧验证码包，清完退出 |
| `--keep-code` | 取完码保留网盘临时目录（调试用） |
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
- 自动启动依赖能找到 `keysteam.exe`：注册表里没记录的绿色版/便携版请手动在
  `config.json` 里把 `keysteam_exe` 写成完整路径；不想自动启动就设 `auto_launch: false` 或用 `--no-launch`。
- 二维码短链有效期约 **20 分钟**，过期返回 HTTP 410；程序会自动点「重新加载二维码」重试。
- 网盘里的验证码包同样约 **20 分钟**换一次内容，所以程序每次都用新的临时目录转存、下完即删
  （详见上文），不会拿到上一次的旧包。
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
| Locate the install path | **Registry / running process / common dirs** | `config.json` → image path of a running `keysteam.exe` → registry uninstall entries (`DisplayIcon` / `InstallLocation`, scanning `HKCU`, `HKLM` and `WOW6432Node`) → `App Paths` → `%LOCALAPPDATA%\KeySteam` and friends → `PATH`. **Works on any machine without editing config**; the hit is written back to `config.json` |
| Launch the app | **Attach if running, launch if not** | Already running → connect to the existing window (no restart, no state change); not running → start the located exe, wait for the control tree, then continue with the QR |
| Locate UI elements | **Windows UI Automation** | Semantic lookup (window `KeySteam 验证`, image `验证码分享链接二维码`, edit `输入中间 6 位数字`, button `验证`). **No coordinates, no version strings** — survives minor UI changes |
| Capture the QR | **PrintWindow** | The window renders itself into a bitmap; works even when occluded or unfocused |
| Decode the QR | OpenCV `QRCodeDetector` | Multiple enhancement passes (upscale / threshold / invert) |
| Resolve landing page | Reimplemented **BigInt-LCG proof-of-work** | `key.steamofl.com/q/<id>` returns 403 for desktop UAs; the page runs `x=(x*a+c)%m` n times and expects the hex answer posted back before revealing the real drive URL |
| Read the drive | Quark `drive-pc` web API | Share token and directory listing are **anonymous**; save-to-drive and download require login |
| Save & fetch the code | **Fresh temp folder per run → download → delete** | The archive is refreshed roughly every 20 minutes **under the same filename**, so each run saves into `KeySteam验证码/run-<time>-<random>/`, downloads, and removes the folder — never re-using a stale copy |
| Obtain login state | **Isolated browser profile + CDP** | Chromium locks the cookie DB while running (WinError 32), so a dedicated profile is launched with `--remote-debugging-port` and cookies are read via the DevTools protocol. The browser itself is chosen by `browser_preference` (`auto` = your default browser when it is Chromium-based, else Chrome → Edge) |
| Extract the code | zipfile / 7-Zip + regex + OCR | Scans the archive for the 6-digit code |
| Submit | ValuePattern + InvokePattern | Same path a human would take |

### Quick start

**One action** — double-click `KeySteamAutoVerify.exe`.

- KeySteam **not running** → the tool finds it via the registry, launches it, waits for the UI, then reads the QR.
- KeySteam **already running** → it attaches to the live window and goes straight to the QR.

The only manual action ever required is the **first-time Quark login** in the
browser window the tool opens. The cookie is captured automatically as soon as
you finish logging in.

> ⚠️ `cookies.json` contains your Quark credentials. Never commit or share it.

### Why every run uses a brand-new folder

The verification archive is re-generated about every **20 minutes**, but it keeps
the **same filename**. Saving it straight into the drive root (the old approach)
breaks on the second run:

1. Run #1 leaves `2026-11-27 验证码.zip` in the root (a good code).
2. Twenty minutes later the server has new content, but saving again hits the
   **same-name file already sitting there** — the download returns the stale copy.
3. Submitting that stale code → KeySteam answers "验证码失效" and the whole run fails.

The current flow:

| Step | Action |
|---|---|
| 1 | Create a unique folder `run-<timestamp>-<6 hex>` under `KeySteam验证码/` (parallel or consecutive runs can never collide) |
| 2 | Save this run's archive **into that empty folder** — no chance of hitting a historical file |
| 3 | Download → extract → read the 6-digit code |
| 4 | Delete the whole temp folder in a `finally` block (success or failure) |
| 5 | Also sweep leftover `*验证码*.zip/.rar/.7z` from older versions and `run-*` folders left by crashes |

After a run the drive only keeps one empty `KeySteam验证码` folder.
Use `--keep-code` to keep the folder for debugging, `--clean-drive` to purge history once.

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
- The archive on the drive is refreshed about every 20 minutes too, which is why
  each run saves into a fresh temp folder and deletes it right after downloading.
- The resulting ticket is valid for **one day**.
- Quark sessions expire eventually — re-run the wizard to refresh.
- Auto-launch needs to find `keysteam.exe`; portable/green builds missing from the
  registry should be pinned via `keysteam_exe` in `config.json`. Set
  `auto_launch: false` or pass `--no-launch` to disable launching.

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
