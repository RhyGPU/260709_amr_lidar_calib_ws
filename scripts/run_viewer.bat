@echo off
REM ============================================================================
REM  run_viewer.bat  -  quick live LiDAR viewer (standalone)
REM
REM  WHAT : Opens a matplotlib window that reads the LiDAR straight from the SEER
REM         API and plots the front+rear points in the robot frame, live.
REM  WHEN : You just want to SEE the LiDAR working. Needs nothing else running
REM         (no emitter, no relay, no calibration app) - it talks to the robot.
REM  USAGE: run_viewer.bat [robot_ip]        default 192.168.44.82 (WiFi)
REM         e.g.  run_viewer.bat 192.168.192.5      (wired)
REM  NOTE : Read-only, no credentials. Close the window to stop.
REM ============================================================================
cd /d "%~dp0.."
set ROBOT=%1
if "%ROBOT%"=="" set ROBOT=192.168.44.82
python -m amr_lidar.viewer %ROBOT%
pause
