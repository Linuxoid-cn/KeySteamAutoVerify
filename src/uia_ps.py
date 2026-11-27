# -*- coding: utf-8 -*-
"""用 PowerShell + .NET UIAutomationClient 做界面操作（冻结版后端）。

为什么需要这个：
    PyInstaller 打包后，comtypes 生成的 IUIAutomation 会退化
    （ElementFromHandle 正常，但 GetFirstChildElement 恒为 NULL），
    而同一台机器上 PowerShell 的 .NET UIA 能正常看到完整控件树。

设计要点：
    * 纯 PowerShell + .NET，**不使用 Add-Type**（打包/受限环境下编译C#会失败）
    * 找窗口用 Get-Process，找 WebView2 渲染宿主用 UIA 的 ClassNameProperty
    * 一次调用一个 powershell 进程，输出一行 JSON
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_SCRIPT = r'''
param([string]$Action = "find", [string]$PayloadB64 = "")

if ([string]::IsNullOrEmpty($PayloadB64)) { $Payload = "{}" }
else { $Payload = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($PayloadB64)) }

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

function Get-Root($hwndValue) {
  # 注意：不用 Get-Process —— 打包后的进程可能无法枚举其他进程，
  # 但窗口枚举是通的，所以句柄由调用方（Python 侧 Win32）传进来。
  $hwnd = [IntPtr][int64]$hwndValue
  if ($hwnd -eq [IntPtr]::Zero) { return $null }

  $win = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
  if ($null -eq $win) { return $null }

  $cond = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ClassNameProperty,
            "Chrome_RenderWidgetHostHWND")
  $rwh = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
  if ($null -eq $rwh) { return $win }
  $h = $rwh.Current.NativeWindowHandle
  if ($h -eq 0) { return $win }
  return [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$h)
}

function Get-All($root) {
  if ($null -eq $root) { return @() }
  $c = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                     [System.Windows.Automation.Condition]::TrueCondition)
  $out = @()
  for ($i = 0; $i -lt $c.Count; $i++) {
    $e = $c.Item($i)
    try {
      $r = $e.Current.BoundingRectangle
      $out += [pscustomobject]@{
        idx  = $i
        type = ($e.Current.ControlType.ProgrammaticName -replace 'ControlType\.','')
        name = [string]$e.Current.Name
        x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height
      }
    } catch {}
  }
  return $out
}

function Pick($items) {
  $gate = $items | Where-Object { $_.type -eq "Window" -and $_.name -like "*KeySteam 验证*" } | Select-Object -First 1

  $imgs = @($items | Where-Object {
      $_.type -eq "Image" -and $_.w -ge 120 -and $_.h -ge 120 -and
      ($_.w / [double][Math]::Max(1,$_.h)) -gt 0.75 -and
      ($_.w / [double][Math]::Max(1,$_.h)) -lt 1.35 })
  if ($gate) {
    $imgs = @($imgs | Where-Object {
      $_.x -ge $gate.x -and ($_.x + $_.w) -le ($gate.x + $gate.w) -and
      $_.y -ge $gate.y -and ($_.y + $_.h) -le ($gate.y + $gate.h) })
  }
  $qr = $null
  if ($imgs.Count -gt 0) {
    $qr = $imgs | Sort-Object `
      @{Expression={ if ($_.name -like "*二维码*") { 1 } else { 0 } }; Descending=$true}, `
      @{Expression={ $_.w * $_.h }; Descending=$true} | Select-Object -First 1
  }

  $edits = @($items | Where-Object { $_.type -eq "Edit" })
  if ($gate) {
    $in = @($edits | Where-Object {
      $_.x -ge $gate.x -and $_.x -le ($gate.x + $gate.w) -and
      $_.y -ge $gate.y -and $_.y -le ($gate.y + $gate.h) })
    if ($in.Count -gt 0) { $edits = $in }
  }
  $input = $null
  $sem = @($edits | Where-Object {
    $_.name -like "*验证码*" -or $_.name -like "*6 位*" -or
    $_.name -like "*6位*" -or $_.name -like "*数字*" })
  if ($sem.Count -gt 0) { $input = $sem | Select-Object -First 1 }
  elseif ($edits.Count -gt 0) { $input = $edits | Sort-Object -Property y -Descending | Select-Object -First 1 }

  $btns = @($items | Where-Object { $_.type -eq "Button" -and $_.name.Trim() -eq "验证" })
  if ($btns.Count -eq 0 -and $gate) {
    $btns = @($items | Where-Object {
      $_.type -eq "Button" -and $_.name -like "*验证*" -and
      $_.x -ge $gate.x -and $_.x -le ($gate.x + $gate.w) })
  }
  if ($btns.Count -gt 0 -and $input) {
    $iy = $input.y + [int]($input.h / 2)
    $tol = [Math]::Max(30, $input.h)
    $row = @($btns | Where-Object {
      [Math]::Abs(($_.y + [int]($_.h/2)) - $iy) -le $tol -and $_.x -ge $input.x })
    if ($row.Count -gt 0) { $btns = $row }
  }
  $button = $null
  if ($btns.Count -gt 0) {
    $button = $btns | Sort-Object -Property @{Expression={ $_.w * $_.h }} | Select-Object -First 1
  }

  return [pscustomobject]@{ gate=$gate; qr=$qr; input=$input; button=$button }
}

function To-Element($root, $idx) {
  $c = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                     [System.Windows.Automation.Condition]::TrueCondition)
  if ($idx -lt 0 -or $idx -ge $c.Count) { return $null }
  return $c.Item($idx)
}

$plTop = $Payload | ConvertFrom-Json
$hwndValue = $plTop.hwnd
$root  = Get-Root $hwndValue
$items = Get-All $root

switch ($Action) {
  "find" {
    $p = Pick $items
    $res = [pscustomobject]@{
      ok = ($null -ne $root); total = $items.Count
      gate = $p.gate; qr = $p.qr; input = $p.input; button = $p.button
      gateVisible = ($null -ne $p.gate)
      dbgHwnd = [string]$hwndValue
      dbgPayloadLen = ([string]$Payload).Length
      dbgRootNull = ($null -eq $root)
    }
  }
  "set" {
    $pl = $Payload | ConvertFrom-Json
    $p  = Pick $items
    if (-not $p.input) { $res = [pscustomobject]@{ ok=$false; reason="no input" } }
    else {
      $e  = To-Element $root $p.input.idx
      $vp = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
      $vp.SetValue([string]$pl.value)
      $res = [pscustomobject]@{ ok=$true; value=[string]$vp.Current.Value }
    }
  }
  "click" {
    $p = Pick $items
    if (-not $p.button) { $res = [pscustomobject]@{ ok=$false; reason="no button" } }
    else {
      $e = To-Element $root $p.button.idx
      $done = $false
      try {
        $ip = $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $ip.Invoke(); $done = $true
        $res = [pscustomobject]@{ ok=$true; how="invoke" }
      } catch {}
      if (-not $done) {
        try { $e.SetFocus(); $res = [pscustomobject]@{ ok=$true; how="focus" } }
        catch { $res = [pscustomobject]@{ ok=$false; reason="invoke failed" } }
      }
    }
  }
  "reload" {
    $b = $items | Where-Object { $_.type -eq "Button" -and $_.name -like "*重新加载*" } | Select-Object -First 1
    if (-not $b) { $res = [pscustomobject]@{ ok=$false; reason="no reload button" } }
    else {
      $e = To-Element $root $b.idx
      $done = $false
      try {
        $ip = $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $ip.Invoke(); $done = $true
      } catch {}
      if (-not $done) { try { $e.SetFocus(); $done = $true } catch {} }
      $res = [pscustomobject]@{ ok=$done; name=$b.name }
    }
  }
  default { $res = [pscustomobject]@{ ok=$false; reason="unknown action" } }
}

$res | ConvertTo-Json -Depth 6 -Compress
'''


_SCRIPT_FILE = None


def _candidate_dirs() -> list[str]:
    dirs = []
    for env in ("TEMP", "TMP", "LOCALAPPDATA", "APPDATA"):
        d = os.environ.get(env)
        if d:
            dirs.append(os.path.join(d, "ksav"))
    dirs.append(os.path.join(tempfile.gettempdir(), "ksav"))
    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(os.path.dirname(sys.executable), "ksav"))
    else:
        dirs.append(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "runs", "ksav"))
    return dirs


def _script_path() -> str:
    """把 PS 脚本落到一个确实能写的目录（逐个尝试）。"""
    global _SCRIPT_FILE
    if _SCRIPT_FILE and os.path.exists(_SCRIPT_FILE):
        return _SCRIPT_FILE

    import uuid
    name = "uia_%s.ps1" % uuid.uuid4().hex[:8]
    last_err = None
    for d in _candidate_dirs():
        try:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8-sig") as f:
                f.write(_SCRIPT)
            _SCRIPT_FILE = p
            return p
        except Exception as e:
            last_err = e
            continue
    raise OSError(f"所有候选目录都写不进去: {last_err}")



def _clean_env() -> dict:
    """给 PowerShell 一个干净环境。

    打包成 exe 后，PyInstaller 会把 _internal 目录塞进 PATH，
    里面有 python312.dll / VCRUNTIME140.dll 等。
    PowerShell 是 .NET 程序，启动时如果从 PATH 捡到这些 DLL，
    COM/UIA 会出现"能拿到元素但遍历不到子节点"的怪现象。
    """
    env = os.environ.copy()
    for k in ("_MEIPASS", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR",
              "_PYI_PARENT_PROCESS_LEVEL", "_PYI_SPLASH_IPC",
              "PYTHONHOME", "PYTHONPATH", "PYTHONIOENCODING"):
        env.pop(k, None)

    strip_dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        strip_dirs.append(os.path.normcase(meipass))
    if getattr(sys, "frozen", False):
        strip_dirs.append(os.path.normcase(os.path.dirname(sys.executable)))
        strip_dirs.append(os.path.normcase(os.path.join(os.path.dirname(sys.executable), "_internal")))

    parts = env.get("PATH", "").split(os.pathsep)
    keep = []
    for p in parts:
        if not p:
            continue
        np = os.path.normcase(os.path.normpath(p))
        if any(np == d or np.startswith(d + os.sep) for d in strip_dirs):
            continue
        keep.append(p)
    env["PATH"] = os.pathsep.join(keep)
    return env


def _powershell() -> str:
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    cand = os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if os.path.exists(cand):
        return cand
    return "powershell.exe"


def run(action: str, payload: dict | None = None, timeout: float = 90.0) -> dict:
    try:
        script = _script_path()
    except Exception as e:
        return {"ok": False, "reason": f"写脚本失败: {e}"}

    import base64 as _b64
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    payload_b64 = _b64.b64encode(payload_json.encode("utf-8")).decode("ascii")
    args = [
        _powershell(), "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File", script,
        "-Action", action,
        "-PayloadB64", payload_b64,
    ]
    # 关键：本程序可能被外层（沙箱 / 作业对象）限制，
    # 导致其子进程拿不到完整的 UIA 树（FindAll 返回 0）。
    # 用 CREATE_BREAKAWAY_FROM_JOB 让 PowerShell 脱离作业对象。
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    proc = None
    last_err = None
    for flags in (CREATE_BREAKAWAY_FROM_JOB, 0):
        try:
            proc = subprocess.run(args, capture_output=True,
                                  timeout=timeout, creationflags=flags,
                                  env=_clean_env())
            break
        except OSError as e:
            last_err = e
            proc = None
            continue
        except FileNotFoundError:
            return {"ok": False, "reason": "找不到 powershell.exe"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "powershell 超时"}

    if proc is None:
        return {"ok": False, "reason": f"启动 powershell 失败: {last_err}"}
    r = proc

    out = r.stdout.decode("utf-8", "replace").strip()
    err = r.stderr.decode("utf-8", "replace").strip()
    if not out:
        return {"ok": False, "reason": "no output", "stderr": err[:900]}
    line = out.splitlines()[-1].strip()
    try:
        return json.loads(line)
    except Exception:
        return {"ok": False, "reason": "bad json", "raw": out[:600], "stderr": err[:600]}
