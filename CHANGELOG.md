# 更新日志 · Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [1.0.3] - 2026-11-27

登录用的浏览器改成跟随系统默认。

### 变更

- **原来**：硬编码顺序 Chrome → Edge → 夸克浏览器。系统默认是 Edge 的机器，
  第一次登录也会弹 Chrome 出来，看着不像"我的浏览器"。
- **现在**：新增 `browser_login_cdp.default_browser()`，读
  `HKCU\...\UrlAssociations\http\UserChoice` 得到默认浏览器的 ProgId，
  再解析它的 `shell\open\command` 拿 exe（读不到就按 ProgId 映射到已知安装目录）。
  默认浏览器是 Chromium 系（Edge / Chrome / Brave / 夸克 / Vivaldi…）就优先用它，
  否则回退 Chrome → Edge。
- 新增配置项 `browser_preference`：`auto`（默认，跟随系统）/ `chrome` / `edge` / 具体 exe 路径。
- 启动日志会先说明默认浏览器是谁、支不支持 CDP，再说明实际用的是哪一个。

> 仍然使用**独立 profile**（`%TEMP%\ksav\profile`），不读也不动日常浏览器的数据；
> `--manual` 手动下载模式本来就是用系统默认浏览器打开分享页，未改动。

实测：本机默认 = `msedge`（`MSEdgeHTM`），`auto` 下实际拉起 `msedge` 并成功通过 CDP 拿到 30 个 cookie。

### 修复

- **启动 KeySteam 时不再让它依赖我们的打包目录**：打包版直接 `Popen` 拉起 KeySteam 时，
  KeySteam 会把 `VCRUNTIME140.dll` 解析到本工具的 `_internal` 里。后果是
  KeySteam 悄悄依赖我们的文件夹（我们一删它就跑不起来），且运行时锁死这些 dll，
  导致本工具无法覆盖更新（实测 `Remove-Item` 报 Access denied）。
  现在改为经 `explorer.exe` 间接启动，DLL 解析回到 `C:\Windows\System32`；
  `_clean_env()` 同时把自身目录从子进程 PATH 里摘掉，直接执行时才走兜底路径。

---

## [1.0.2] - 2026-11-27

双击就干活：自己找到 KeySteam、没开就自己开、开着就直接扫二维码。

### 新增

- **自动定位安装位置**（新增 `src/locate.py`）：依次尝试
  `config.json` → 正在运行的 `keysteam.exe` 镜像路径 →
  注册表卸载项的 `DisplayIcon` / `InstallLocation`（`HKCU`、`HKLM`、`WOW6432Node` 全扫）→
  注册表 `App Paths` → `%LOCALAPPDATA%\KeySteam` 等常见目录 → `PATH`。
  命中后自动写回 `config.json`，**换机器、换安装盘都不用改配置**。
- **没开就自动启动**（`app.ensure_window`）：已运行则直接接管现有窗口（不重启、不改状态），
  未运行则用定位到的 exe 启动并等界面就绪，然后继续扫二维码。
- 配置项 `auto_launch` / `launch_wait_seconds`，命令行 `--no-launch`。
- **控制台配色**：标题亮青色，仓库网址青色，作者名洋红，双击运行时一眼看到出处。

### 修复

- `attach()` 之前只要控件数非 0 就返回，自动启动后常常只拿到 1 个壳控件就没下文；
  现在要等到「验证弹窗 / 二维码出现」或控件数 ≥ 20 才算连上。
- 新增 `app.wait_for_gate()`：刚启动时弹窗可能晚一两秒出现，避免误判「已解锁、不需要验证」。
- 向导步骤顺序调整为：1 启动/接管 → 2 读二维码 → 3 检查登录 → 4 取码 → 5 提交
  （原来是 2→3→1→4→5，看着别扭）。

---

## [1.0.1] - 2026-11-27

取码逻辑重写：验证码包约 20 分钟换一次内容、文件名却不变，
旧版每次转存到网盘根目录，第二次会命中上一次的旧包 → 提交旧码必然「验证码失效」。

### 修复

- **删除接口参数纠错（实测踩了两个坑）**：夸克 `/file/delete` 只认 `filelist`，
  写成 `file_list` 报 `14001 Bad Parameter: [current_dir_fid,filelist 不能同时为空]`；
  而 `filelist` 和 `current_dir_fid` 又**不能同时给**，给了报 `[... 不能同时存在值]`。
  现在固定只传 `{"action_type": 2, "filelist": [...], "exclude_fids": []}`。
- **清理数量不再谎报**：删除失败时返回 0，不再把"准备删"的数量当成"已删"。
- **同名旧包导致验证码失效**：每次运行都在 `KeySteam验证码/` 下新建唯一目录
  `run-<时间戳>-<6位随机>`，只把本次的包转存进这个空目录，因此不可能撞到历史文件。
- **用完即删**：`fetch_code_zip` 的 `finally` 里删除整个临时目录，成功失败都清理，
  网盘不会留下任何旧验证码包。
- **历史残留自动清理**：取码前扫一遍根目录，删掉旧版本遗留的 `*验证码*.zip/.rar/.7z`；
  并清掉上次崩溃/中断留下的 `run-*` 临时目录。
- **转存后定位更可靠**：在目标目录内按文件名匹配，匹配不到就退回「目录里最新的压缩包」，
  不再在根目录里瞎找。
- **下载内容判空**：空响应直接报错，不会把空文件当验证码包解压。

### 新增

- `--clean-drive`：只清理网盘里遗留的旧验证码包，清完退出。
- `--keep-code`：取完码保留网盘临时目录，仅调试用。
- 配置项 `quark_save_dir`（临时目录的父目录，默认 `KeySteam验证码`）
  与 `quark_cleanup`（是否取完就删，默认 `true`）。
- `config.resolve()` 支持 `%LOCALAPPDATA%` 这类环境变量，
  `keysteam_exe` 默认值不再写死某台机器的绝对路径。

---

## [1.0.0] - 2026-11-27

第一个可用的正式版本。全流程端到端验证通过。

### 新增

- **交互向导**：双击即运行，无需任何命令行参数。5 步进度提示，全中文自然语言反馈。
- **UI Automation 语义定位**：按控件语义而不是坐标/版本号找元素，界面小改仍可命中。
  - 窗口：`KeySteam 验证`
  - 二维码：`验证码分享链接二维码`
  - 输入框：`输入中间 6 位数字，也可粘贴完整验证码`
  - 按钮：`验证`
- **PrintWindow 抓图**：窗口被遮挡或失焦时仍能正确截取二维码。
- **二维码解码**：OpenCV 多轮增强（放大 2/3/4/6 倍、四档二值化、反色）。
- **跳板页工作量证明求解**：复刻页面的 BigInt-LCG 迭代逻辑，纯 Python 实现，无需真机扫码。
- **夸克网盘客户端**：分享解析、stoken、目录遍历、转存、任务轮询、直链下载。
- **浏览器登录引导**：独立 profile + CDP 读取 cookie，绕开 Chromium 的 cookie 数据库独占锁。
- **验证码提取**：zip/rar/7z 解包，文本扫描 + 可选 OCR，取「中间 6 位数字」。
- **自动提交**：ValuePattern 写值 + InvokePattern 点击，并轮询弹窗是否消失。

### 修复

- GDI 句柄未声明 `restype/argtypes` 导致 64 位下 `OverflowError`。
- 冻结版（PyInstaller）中 comtypes 的 IUIAutomation 退化，改为 PowerShell + .NET UIA 后端。
- 夸克登录 cookie 实际为双下划线命名（`__kps` / `__puus` / `__uid`），修正登录判定。
- 二维码短链过期（HTTP 410）时自动「重新加载二维码」并重试。
- 非交互环境下倒计时刷屏，改为节流输出。
- 结果提示行变量名拼写错误导致 `NameError`。

### 已知限制

- 仅支持 Windows。
- 二维码短链约 20 分钟失效，票据有效期一天。
- 夸克登录态过期后需重新走一次登录引导。

---

## 开发历程 · Development milestones

这个项目不是一次写完的，下面记录几个关键转折，供后来者参考。

### 阶段 1：静态分析（确定门控结构）

从 `keysteam.exe`（v3.3.2，Rust + Tauri + WebView2）中提取出三层门控：

1. **云端授权**：`key.steamofl.com/api/*`
2. **本地加密票据**：`%APPDATA%\ShikiKawaii\verification.cache`，`KSTK` 容器，
   实测 669 字节定长、AEAD 加密、含 `sig01` 签名
3. **功能位分叉**：成人内容标记、入库额度、清单版本锁

实测结论：票据由服务端签发且每天重新生成，本地无法伪造。

### 阶段 2：放弃的路线

| 路线 | 结论 |
|---|---|
| 篡改本地票据延长有效期 | 无效：AEAD 解密失败即被忽略 |
| 伪造 `/api/update` 响应 | 无效：minisign 验签 |
| 修改本地版本号绕过更新提示 | 能骗过版本闸，但与验证码链路无关 |
| 回退到旧版本 | 服务端 `min_version` 已顶到最新 |
| 走 CDP 调试端口控制 WebView2 | 无效：Tauri 覆盖 `AdditionalBrowserArguments` |

### 阶段 3：转向「自动化人工操作」

既然门控无法绕过，就改为**替人把这套流程跑完**——于是有了本项目。

关键突破：

- **UIA 而不是 CDP**：Tauri 不让开调试端口，但 WebView2 会把 DOM 映射成无障碍树。
- **PrintWindow 而不是屏幕截图**：不抢焦点、不受遮挡。
- **解工作量证明而不是真机扫码**：跳板页的 JS 挑战可以纯 Python 复刻。
- **独立 profile + CDP 拿 cookie**：绕开 Chromium 的 cookie 数据库独占锁。

### 阶段 4：端到端验证

2026-11-27 实测完整流程成功：

```
✓ 二维码识别 -> pan.quark.cn/s/xxxxxxxx
✓ 浏览器登录 -> cookies.json（31 项，含 __kps/__puus/__uid）
✓ 转存 + 下载 -> 2026-11-27 验证码.zip（759 字节）
✓ 提取验证码 -> xxxxxx
✓ 提交 -> 验证弹窗已消失
```

同日确认了官方说明：二维码有效期 20 分钟，**激活后验证有效期一天**。
