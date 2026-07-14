import socket, struct, threading, time, subprocess

MARKER = b'MS3 '
HDR = 24

def ping(ip):
    r = subprocess.run(['ping','-n','2','-w','800',ip], capture_output=True, text=True)
    return ('TTL=' in r.stdout) or ('ttl=' in r.stdout)

for ip in ('192.168.192.100','192.168.192.101'):
    print(f'ping {ip}: {"ALIVE" if ping(ip) else "no reply"}')

caught = {}
def listen(port, dur=8.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', port))
    except OSError as e:
        print(f'port {port} bind fail: {e}'); return
    s.settimeout(1.0)
    t0=time.time()
    while time.time()-t0 < dur:
        try:
            data, addr = s.recvfrom(65535)
        except socket.timeout:
            continue
        if data[:4]==MARKER and len(data)>=HDR+16:
            off=HDR
            serial = struct.unpack('<I', data[off+4:off+8])[0]
            ver = f'{data[off+1]}.{data[off+2]}.{data[off+3]}'
            key=(addr[0],port)
            if key not in caught:
                caught[key]={'serial':serial,'ver':ver,'count':0,'bytes':0}
                print(f'  >>> CAUGHT nanoScan3 packet: src={addr[0]}:{addr[1]} -> local:{port} serial={serial} fw={ver}')
            caught[key]['count']+=1
            caught[key]['bytes']+=len(data)
    s.close()

print('\nListening on UDP 6060 (front) and 6061 (rear) for MS3 datagrams (8s)...')
threads=[threading.Thread(target=listen,args=(p,)) for p in (6060,6061)]
for t in threads: t.start()
for t in threads: t.join()

print('\n=== DETECTION SUMMARY ===')
if caught:
    for (ip,port),v in caught.items():
        print(f'  {ip} -> port {port}: {v["count"]} datagrams, {v["bytes"]} bytes, serial={v["serial"]}, fw={v["ver"]}  [CONNECTED]')
else:
    print('  No MS3 datagrams received at this PC.')
    print('  (Sensors likely stream UDP unicast to the AMR PC 192.168.192.5, not to us;')
    print('   on a switched LAN that traffic is not flooded to 192.168.192.13.)')
