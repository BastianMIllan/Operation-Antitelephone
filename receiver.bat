@echo off
rem Opens the Operation Antitelephone receiver full screen in Windows Terminal, and restarts it if it ever crashes.
rem Extra options are passed on, for example:  receiver.bat --demo   or   receiver.bat --fps 2
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
if "%~1"=="--loop" goto loop
where wt >nul 2>nul
if not errorlevel 1 (
  start "" wt -F new-tab --title "ANTITELEPHONE RECEIVER" -d "%~dp0." cmd /c receiver.bat --loop %*
  exit /b
)
:loop
set "ARGS=%*"
if defined ARGS set "ARGS=%ARGS:--loop=%"
:again
%PY% receiver.py %ARGS%
if not errorlevel 1 exit /b
echo The receiver stopped with an error. Restarting in 10 seconds (close this window to stop).
timeout /t 10 >nul
goto again
