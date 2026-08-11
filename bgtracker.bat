@echo off
REM Double-click to start the overlay. Keep Hearthstone in BORDERLESS WINDOWED.
REM Options pass straight through, e.g.:  bgtracker.bat --mmr 10 --time past-seven
cd /d "%~dp0"

REM Launched with python (not pythonw) and a minimised console. pythonw on PATH
REM is the Microsoft Store alias rather than the interpreter everything else
REM here runs on, and chasing the real one gained nothing but a window that
REM never appeared. A minimised console is boring and it works.
start /min "bgtracker" python overlay.py %*
