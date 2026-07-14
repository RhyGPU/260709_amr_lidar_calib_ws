@echo off
REM ============================================================================
REM  run_ms3_subscriber.bat  -  subscribe to the raw-MS3 emitter (holds the lease)
REM
REM  WHAT : Authenticates to the emitter (id/pw) and pings to stay subscribed,
REM         so the emitter keeps unicasting raw MS3 to THIS PC ports 6060/6061.
REM         The calibration app receives that MS3 unchanged.
REM  WHEN : Start AFTER run_ms3_emitter.bat, alongside run_calibration_app.bat.
REM  EMITTER: 127.0.0.1 if the emitter runs on THIS PC; else its LAN IP.
REM         ID/PW/CTRL must match the emitter. Close the window to unsubscribe.
REM ============================================================================
cd /d "%~dp0.."
set EMITTER=127.0.0.1
set CTRL=6099
set ID=amr
set PW=lidar2026
python -m amr_lidar.ms3_subscriber %EMITTER% --control-port %CTRL% --id %ID% --pw %PW% --front-port 6060 --rear-port 6061
pause
