@echo off
REM ============================================================================
REM  run_relay_server.bat  -  authenticated UDP relay (fan-out to many clients)
REM
REM  WHAT : Holds ONE connection to the SEER API and RE-PUBLISHES the LiDAR over
REM         UDP to any number of clients that log in with an id/password.
REM  WHEN : You want your OWN programs (not the calibration app) to receive the
REM         LiDAR, possibly several at once, without each hitting the robot API.
REM  USAGE: run_relay_server.bat        (edit SEER/PORT/ID/PW below to change)
REM         Clients connect with run_relay_client.bat <this-PC-ip>.
REM  CREDS: id=amr  pw=lidar2026  port=6900   (change here; keep CONNECTIONS.txt
REM         in sync). Binds 0.0.0.0 so it's reachable on all this PC's IPs.
REM  NOTE : This is a DIFFERENT protocol than the calibration app (which needs
REM         the MS3 emitter/bridge, not this relay).
REM ============================================================================
cd /d "%~dp0.."
set SEER=192.168.44.82
set PORT=6900
set ID=amr
set PW=lidar2026
python -m amr_lidar.relay_server --seer %SEER% --port %PORT% --id %ID% --pw %PW% --hz 10
pause
