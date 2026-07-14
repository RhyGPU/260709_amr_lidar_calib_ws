import socket, struct, json, sys

def req(sock, api_type, payload=None):
    body = b'' if payload is None else json.dumps(payload).encode('utf-8')
    header = struct.pack('>BBHIH6s', 0x5A, 0x01, 1, len(body), api_type, b'\x00'*6)
    sock.sendall(header + body)
    # read 16-byte header
    hdr = b''
    while len(hdr) < 16:
        c = sock.recv(16-len(hdr))
        if not c: raise IOError('closed during header')
        hdr += c
    sync, ver, num, length, rtype = struct.unpack('>BBHIH', hdr[:10])
    data = b''
    while len(data) < length:
        c = sock.recv(length-len(data))
        if not c: break
        data += c
    return rtype, json.loads(data.decode('utf-8')) if data else {}

def try_host(ip, port=19204, timeout=2.0):
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.settimeout(timeout)
        return s
    except Exception as e:
        return None

hosts = ['192.168.192.4','192.168.192.5','192.168.192.7','192.168.192.12']
found = None
for ip in hosts:
    s = try_host(ip)
    if s:
        print(f'[+] {ip}:19204 CONNECTED (SEER Status API)')
        found = (ip, s)
        break
    else:
        print(f'[-] {ip}:19204 no connection')

if not found:
    print('NO SEER CONTROLLER FOUND on 19204')
    sys.exit(1)

ip, s = found
# 1000 = robot info / 1004 = location; do a basic status first (1000)
try:
    rt, info = req(s, 1000)
    print(f'\n[robot info 1000] ret={info.get("ret_code")} model={info.get("model")} '
          f'id={info.get("id")} version={info.get("version")}')
except Exception as e:
    print('info query failed:', e)

# 1009 laser status inquiry
rt, laser = req(s, 1009, {"return_beams3D": False})
print(f'\n[laser 1009] response_type={rt} ret_code={laser.get("ret_code")} err={laser.get("err_msg")!r}')
lasers = laser.get('lasers', [])
print(f'Number of laser devices reported: {len(lasers)}')
for i, L in enumerate(lasers):
    di = L.get('device_info', {})
    beams = L.get('beams', [])
    valid = sum(1 for b in beams if b.get('valid'))
    dists = [b.get('dist') for b in beams if b.get('valid') and b.get('dist') is not None]
    print(f'  Laser #{i}: name={di.get("device_name")!r} freq={di.get("scan_freq")}Hz '
          f'range={di.get("min_range")}-{di.get("max_range")}m angle={di.get("min_angle")}..{di.get("max_angle")} '
          f'| beams={len(beams)} valid={valid} '
          f'| dist[min/max]={min(dists) if dists else None}/{max(dists) if dists else None}')
s.close()
