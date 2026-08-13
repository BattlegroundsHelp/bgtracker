@echo off
REM Runs the dc/rc trial as Administrator.
REM
REM SetTcpEntry refuses to close a socket without elevation, so an unelevated
REM trial can only ever prove the RESTART rung. Elevating the whole trial once
REM is also what keeps the bench honest: no UAC prompt lands in the middle of a
REM timed reconnect and inflates the number we are trying to measure.

net session >nul 2>&1
if %errorlevel%==0 goto run

powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
exit /b

:run
cd /d "%~dp0.."
python tools\dcrc_trial.py
pause
