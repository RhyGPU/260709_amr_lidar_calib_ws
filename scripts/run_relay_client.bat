@echo off
REM ============================================================================
REM  run_relay_client.bat  -  subscribe to the UDP relay and view it
REM
REM  WHAT : Logs into run_relay_server with id/pw, receives the published LiDAR
REM         stream, and shows it live (or prints stats).
REM  WHEN : To test/consume the relay from this or another machine.
REM  USAGE: run_relay_client.bat [relay_host_ip]
REM             relay_host_ip = IP of the PC running run_relay_server
REM             (127.0.0.1 if the server is on THIS PC). Default 127.0.0.1.
REM  CREDS: id=amr  pw=lidar2026  port=6900  (must match the server).
REM  NOTE : Add --no-gui inside the python line for headless stats only.
REM ============================================================================
cd /d "%~dp0.."
set HOST=%1
if "%HOST%"=="" set HOST=127.0.0.1
python -m amr_lidar.relay_client %HOST% --port 6900 --id amr --pw lidar2026
pause
