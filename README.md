# AMR 2D LiDAR Calibration Workspace  (`260709_amr_lidar_calib_ws`)

Live access to the Foil_A082 AMR's 2D LiDAR (4× SICK TiM320-0131000S02, used for
safety + mapping + navigation) through the **SEER Robot Status API**, with three
delivery paths: a direct viewer, a SICK-MS3 UDP emitter for the calibration app,
and a general UDP publishing relay.

> **New here?** Read **`DIRECTORY_GUIDE.txt`** (what every folder is + the layout
> philosophy) and **`COMMANDS.txt`** (organized command reference). This README is
> the entry point; it links out rather than duplicating those.

## The robot / data path

- LiDAR is read from the SEER API — message **1009** (`robot_status_laser_req`),
  TCP port **19204**. Reported as devices `FrontLiDAR` and `RearLiDAR`.
- **No credentials** are needed to read the robot LiDAR — the SEER API is open on
  the robot network. Just the robot IP:
  - `192.168.44.82`  (facility WiFi; this PC = 192.168.44.21)
  - `192.168.192.5`  (wired robot LAN; this PC = 192.168.192.13)
- This is the same source RoboShop Pro uses.

## Layout

```
260709_amr_lidar_calib_ws/
├── amr_lidar/            # THE PACKAGE (ships): seer_client, viewer, ms3_emitter,
│                         #   relay_server, relay_client  — run `python -m amr_lidar.X`
├── apps/                # self-contained sub-projects
│   └── lidar_2d_calibration/   # the modified calibration GUI (see below)
├── scripts/             # one-click .bat launchers
├── tools/               # standalone diagnostics from the investigation (archival)
├── reference/           # READ-ONLY vendor material: seer-api.pdf, TiM3xx manual
├── artifacts/           # generated outputs: amr_scan_view.html, captured scans
├── docs/                # knowledge & records (domain-partitioned) — see docs/README.md
│   ├── protocol/        #   UDP relay + MS3 wire format
│   ├── worklog/         #   dated work logs
│   ├── issues_and_fixes/#   bug/fix records
│   └── code_updates/    #   file-level change log
├── keys/                # SSH keypair (gitignored)
├── logs/                # run logs / captures (gitignored)
├── DIRECTORY_GUIDE.txt  # full folder guide + philosophy
├── COMMANDS.txt         # organized command reference
├── pyproject.toml
└── requirements.txt
```
Full explanation of every folder and the reasoning: **`DIRECTORY_GUIDE.txt`**.

## Requirements
`pip install -r requirements.txt`  (numpy, matplotlib — already installed here).

## Usage

### 1. Direct viewer
```
python -m amr_lidar.viewer 192.168.44.82
```
or double-click `scripts/run_viewer.bat`.

### 2. Feed the calibration app (`apps/lidar_2d_calibration`)  (SICK MS3 UDP)
That app is a passive MS3 listener — its Network (UDP) panel takes an **ip:port**
per sensor (no id/pw). The emitter streams the SEER LiDAR to those ports in the
SICK format the app already parses:
```
python -m amr_lidar.ms3_emitter --seer 192.168.44.82 \
    --front 192.168.44.21:6060 --rear 192.168.44.21:6061 --hz 10
```
Then in the app enter **Front `192.168.44.21:6060`**, **Rear `192.168.44.21:6061`**
and click **Reconnect**. (Verified: the app's own NanoScan3Receiver decodes it —
520 pts, ~450 valid.) Launcher: `scripts/run_ms3_emitter.bat`.

### 3. General UDP relay (authenticated fan-out)
For your own clients: one relay holds the SEER connection and publishes to many
UDP subscribers that authenticate with id/pw (default `amr` / `lidar2026`, port
6900). See `docs/protocol/README.md`.
```
python -m amr_lidar.relay_server --seer 192.168.44.82 --port 6900 --id amr --pw lidar2026
python -m amr_lidar.relay_client 192.168.44.21 --port 6900 --id amr --pw lidar2026
```
Launchers: `scripts/run_relay_server.bat`, `scripts/run_relay_client.bat`.

## Bundled calibration app (modified copy)

`apps/lidar_2d_calibration/` is a copy of your calibration app, fixed (the original
in Downloads is untouched). See `docs/issues_and_fixes/003-lidar-view-disappears-on-jog.md`.
- **`ui/scan_canvas.py`** — **root-cause crash fix**: `paintEvent` called
  `QPainter.drawPolygon(QPointF, QPointF, QPointF)`, which PySide6 rejects
  (`TypeError`). It only fired once a jog/flip/Load-TF set the sensor marker, so
  changing an angle killed *all* rendering permanently. Now uses `QPolygonF([...])`.
- **`config/sensors.yaml`** — `max_range_m` 5.0 → **40.0** (TiM320 sees far past 5 m).
- **`ui/scan_canvas.py`** — robust auto-fit (median/percentile framing, ignores stray
  far returns; manual zoom/pan disables it; reset-view re-enables).

Run it: start `scripts/run_ms3_emitter.bat`, then `scripts/run_calibration_app.bat`,
then in the app enter Front `192.168.44.21:6060` / Rear `192.168.44.21:6061` → Reconnect.
(Close any other instance first — only one process can bind ports 6060/6061.)

## Which one do I want?
- **Use your calibration app** → path 2 (MS3 emitter). No credentials, no app changes.
- **Quick look** → path 1 (viewer).
- **Share to arbitrary clients with auth** → path 3 (relay).

Keep poll/publish rate ≤ 10 Hz (the SEER API asks for ≥100 ms between requests).
