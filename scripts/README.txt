================================================================================
 scripts/  —  what each launcher does
 Double-click a .bat, or run it from a terminal. All resolve paths relative to
 themselves, so they work from anywhere. Each .bat also has a header comment
 inside it with the same info.
================================================================================

PICK ONE BY GOAL
--------------------------------------------------------------------------------
  Just look at the LiDAR ................... run_viewer.bat
  Run the calibration app on THIS PC ....... run_ms3_emitter.bat  + run_calibration_app.bat
  Feed a specific other PC ................. run_ms3_emitter.bat  (set FRONT/REAR to its IP)
  Feed your OWN programs (with login) ...... run_relay_server.bat + run_relay_client.bat

--------------------------------------------------------------------------------
 run_viewer.bat
--------------------------------------------------------------------------------
  Standalone live viewer. Reads the LiDAR straight from the SEER API and plots
  front+rear points in a matplotlib window. Needs nothing else running.
    run_viewer.bat [robot_ip]      default 192.168.44.82 (WiFi); or 192.168.192.5

--------------------------------------------------------------------------------
 run_ms3_emitter.bat        (feed the calibration app — UNICAST)
--------------------------------------------------------------------------------
  Pulls the LiDAR from the SEER API and re-sends it as SICK "MS3 " UDP to THIS
  PC's ports 6060 (front) / 6061 (rear) — the format the calibration app parses.
  Start this BEFORE run_calibration_app.bat. In the app's Network(UDP) panel:
      Front 192.168.44.21:6060   Rear 192.168.44.21:6061   -> Reconnect
  Unicast to one PC. The OS reassembles IP fragments, so a full scan (>1 MTU)
  arrives intact — no flicker. To feed a different PC, set FRONT/REAR to its IP.
  No credentials.

--------------------------------------------------------------------------------
 run_calibration_app.bat    (the calibration GUI)
--------------------------------------------------------------------------------
  Launches apps\lidar_2d_calibration (PySide6). Our fixes: paintEvent crash fix
  (jog/angle no longer wipes the view), 40 m range cap, auto-fit framing.
  Start a feed first (emitter or bridge). Only ONE process may bind 6060/6061 —
  close other instances first. The app is a passive UDP listener (no id/pw).
  Workflow: Reconnect -> draw Calibration Regions -> Run Calibration (ICP).

--------------------------------------------------------------------------------
 run_relay_server.bat       (authenticated UDP relay — the ONLY thing with creds)
--------------------------------------------------------------------------------
  Holds ONE SEER API connection and re-publishes the LiDAR over UDP to any
  number of clients that log in. For YOUR OWN programs (NOT the calibration app,
  which uses the emitter/bridge instead — different protocol).
      id = amr    pw = lidar2026    port = 6900   (edit in the .bat; keep
      CONNECTIONS.txt in sync). Binds 0.0.0.0 (reachable on all this PC's IPs).

--------------------------------------------------------------------------------
 run_relay_client.bat       (subscribe to the relay)
--------------------------------------------------------------------------------
  Logs into the relay and shows the stream live (or stats).
      run_relay_client.bat [relay_host_ip]   (IP of the PC running the server;
      127.0.0.1 if same PC). Must use the same id/pw/port as the server.

================================================================================
 DATA PATH (all launchers share this)
   SICK TiM320 x4  ->  SEER API (robot, TCP 19204)  ->  [these scripts]  ->  you
   The SEER API needs NO credentials; only the relay (run_relay_*) uses id/pw.
   More: ..\CONNECTIONS.txt (endpoints/creds), ..\COMMANDS.txt (raw commands),
         ..\DIRECTORY_GUIDE.txt (whole workspace).
================================================================================
