@echo off
cd /d "%~dp0"
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --windowed --onefile --name MyCharSync mychar_sync.py
echo.
echo Готово: dist\MyCharSync.exe
pause
