@echo off
REM Double-click to start the overlay. Keep Hearthstone in BORDERLESS WINDOWED.
REM Options pass straight through, e.g.:  bgtracker.bat --mmr 10 --time past-seven
cd /d "%~dp0"

REM No Python? Say so instead of flashing a window and vanishing. The usual
REM cause is the Microsoft Store alias: "python" exists on PATH but only opens
REM the Store page, so the launch silently does nothing and looks like a broken
REM app. Test for a real interpreter before trying to run anything.
python -c "import sys" >nul 2>&1
if errorlevel 1 goto nopython

REM Tkinter ships with python.org builds but is missing from some slim ones,
REM and its absence would otherwise surface as an import traceback in a window
REM that closes too fast to read.
python -c "import tkinter" >nul 2>&1
if errorlevel 1 goto notk

REM Launched with python (not pythonw) and a minimised console. pythonw on PATH
REM is the Microsoft Store alias rather than the interpreter everything else
REM here runs on, and chasing the real one gained nothing but a window that
REM never appeared. A minimised console is boring and it works.
start /min "bgtracker" python overlay.py %*
goto :eof

:nopython
echo.
echo   Python was not found, so this launcher cannot start the overlay.
echo.
echo   You do not need Python at all. Download the ready to run build:
echo     https://github.com/BattlegroundsHelp/bgtracker/releases
echo   Unzip it and run bgtracker.exe instead of this file.
echo.
echo   If you would rather run from source, install Python 3.10 or newer from
echo   python.org (not the Microsoft Store version, its "python" command is an
echo   alias that opens the Store and never runs anything).
echo.
pause
goto :eof

:notk
echo.
echo   Python is installed but tkinter is missing, so the overlay cannot draw.
echo.
echo   Easiest fix: use the ready to run build, which needs no Python:
echo     https://github.com/BattlegroundsHelp/bgtracker/releases
echo.
echo   To fix the source setup instead, reinstall Python from python.org and
echo   leave "tcl/tk and IDLE" ticked in the installer.
echo.
pause
goto :eof
