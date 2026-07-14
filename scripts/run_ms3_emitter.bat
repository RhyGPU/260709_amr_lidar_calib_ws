@echo off
REM ============================================================================
REM  run_ms3_emitter.bat  -  raw-MS3 emitter (SUBSCRIBE / PULL, auth-gated)
REM
REM  WHAT : Pulls the LiDAR from the SEER API and serves it as raw SICK "MS3 "
REM         UDP -- but ONLY to clients that auth with id/pw and keep pinging.
REM         Nothing is broadcast; with zero subscribers nothing is sent.
REM  WHEN : Run this once (the "server"). Then run run_ms3_subscriber.bat on
REM         each PC that should receive, and start run_calibration_app.bat.
REM  PORTS: control (auth/ping) = 6099 ; data unicast to each sub on 6060/6061.
REM  NOTE : Change ID/PW below from the defaults. Close the window to stop.
REM ============================================================================
cd /d "%~dp0.."
set SEER=192.168.44.82
set CTRL=6099
set ID=amr
set PW=lidar2026
python -m amr_lidar.ms3_emitter --seer %SEER% --control-port %CTRL% --id %ID% --pw %PW% --hz 10
pause
