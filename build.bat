@echo off
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -q -r requirements.txt pyinstaller

pyinstaller --noconfirm --onefile --windowed ^
  --name loco_box ^
  --collect-all customtkinter ^
  --hidden-import=PIL._tkinter_finder ^
  main.py

echo.
echo Done: dist\loco_box.exe
pause
