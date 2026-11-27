@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo  KeySteam 验证码自动化 - 打包
echo ============================================

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name KeySteamAutoVerify ^
  --collect-all uiautomation ^
  --hidden-import comtypes ^
  --hidden-import comtypes.stream ^
  --distpath dist ^
  --workpath build ^
  --specpath build ^
  src\main.py

if errorlevel 1 (
  echo.
  echo [失败] 打包出错
  pause
  exit /b 1
)

echo.
echo [完成] 输出: dist\KeySteamAutoVerify.exe
copy /y cookies.example.json dist\cookies.example.json >nul 2>&1
echo.
echo 使用前请把 cookies.json 放到 exe 同目录。
pause
