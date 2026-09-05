@echo off
rem ============================================================
rem  Сборка zapret-warp.exe под Windows
rem  Запускать из папки проекта (от обычного пользователя).
rem ============================================================
chcp 65001 > nul
cd /d "%~dp0"

echo [1/2] Установка PyInstaller...
python -m pip install --upgrade pyinstaller || goto :err

echo [2/2] Сборка...
python -m PyInstaller zapret-warp.spec --noconfirm --clean || goto :err

echo.
echo Готово: dist\zapret-warp.exe
echo.
echo Совет: если положить рядом с exe папки bin\ lists\ strategies\
echo (из этого проекта), то списки и стратегии можно будет править
echo без пересборки.
pause
exit /b 0

:err
echo.
echo ОШИБКА при сборке.
pause
exit /b 1
