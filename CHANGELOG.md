# 更新日志 · Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
This project adheres to [Semantic Versioning](https://semver.org/).

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
