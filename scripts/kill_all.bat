@echo off
REM ============================================================================
REM  kill_all.bat  -  terminate ALL AMR LiDAR background processes
REM
REM  Kills the raw-MS3 emitter, the subscriber, the relay, and any calibration
REM  app (app.py) still running -- including orphaned/background instances that
REM  hog UDP ports 6060/6061. Safe: matches on command line, leaves other python
REM  alone. Double-click this, or run it, whenever the app "shows nothing" or a
REM  stray instance is suspected.
REM ============================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_all.ps1"
pause
