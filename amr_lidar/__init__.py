"""AMR 2D LiDAR access via the SEER Robot Status API.

Modules
-------
seer_client   : TCP client for the SEER API + beam->base_link transform (shared).
viewer        : live matplotlib viewer reading directly from the SEER API.
relay_server  : pulls from the SEER API and re-publishes over UDP to authed clients.
relay_client  : authenticates to the relay, receives the UDP stream, visualizes it.

Run modules with ``python -m amr_lidar.<module>``.
"""

__version__ = "1.0.0"
