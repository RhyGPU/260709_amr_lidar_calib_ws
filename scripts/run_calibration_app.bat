@echo off
REM ============================================================================
REM  run_calibration_app.bat  -  launch the 2D LiDAR ICP calibration GUI
REM
REM  WHAT : Starts the PySide6 calibration app (apps\lidar_2d_calibration).
REM         Includes our fixes: paintEvent crash fix (jog/angle no longer wipes
REM         the view), 40 m range cap, and auto-fit framing.
REM  WHEN : To align front vs rear LiDAR (draw regions -> Run Calibration -> ICP).
REM  USAGE: 1) Start a feed first: run_ms3_emitter.bat (same PC) or
REM            run_lidar_bridge.bat (any PC).
REM         2) Run this.
REM         3) Network(UDP) panel: Front 192.168.44.21:6060 / Rear :6061 -> Reconnect.
REM  NOTE : Only ONE process may bind ports 6060/6061 - close other app instances
REM         first. The app is a passive UDP listener (no id/pw).
REM ============================================================================
cd /d "%~dp0..\apps\lidar_2d_calibration"
python app.py
pause
