# UDP relay wire protocol

The relay (`amr_lidar.relay_server`) publishes the AMR's 2D LiDAR to authenticated
UDP clients. Default endpoint: **UDP port 6900**, credentials **id `amr` / pw `lidar2026`**.

## Control channel (client -> server, JSON, one datagram)

| Message | Purpose | Server reply |
|---------|---------|--------------|
| `{"cmd":"auth","id":"<id>","pw":"<pw>"}` | subscribe | `{"status":"ok","hz":N,"lease":S}` or `{"status":"denied"}` |
| `{"cmd":"ping"}` | renew lease (send every ~lease/3 s) | none (or `{"status":"reauth"}` if unknown) |
| `{"cmd":"bye"}` | unsubscribe | none |

A subscription expires `lease` seconds (default 10) after the last auth/ping.

## Data channel (server -> client, binary, one datagram per scan frame)

All integers little-endian. Points are base_link XY in **meters** (float32), with
every laser device fused into the one robot frame.

```
offset  type        field
0       char[4]     magic = "LDR1"
4       uint32      seq          (frame counter)
8       uint32      t_ms         (server monotonic ms, wraps)
12      uint8       ndev         (number of laser devices)
13      ...         devices[]:
            uint8   name_len
            char[]  name         (name_len bytes, utf-8)
            uint16  npts
            float32 x, float32 y   (repeated npts times)
```

Minimal client: send the `auth` datagram, read the `ok` reply, then `recvfrom`
data datagrams and parse per the table above; send `ping` on a timer. Reference
implementation: `amr_lidar/relay_client.py` (`decode_frame`).
