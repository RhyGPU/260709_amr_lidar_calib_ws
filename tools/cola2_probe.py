import socket, struct, sys
STX=b'\x02\x02\x02\x02'
def frame(sid,rid,cmd,data=b''):
    body=struct.pack('>IH',sid,rid)+cmd+data
    return STX+struct.pack('>I',len(body))+body
def recvt(s):
    hdr=b''
    while len(hdr)<8:
        c=s.recv(8-len(hdr))
        if not c: return None
        hdr+=c
    if hdr[:4]!=STX: return None
    ln=struct.unpack('>I',hdr[4:8])[0]
    b=b''
    while len(b)<ln:
        c=s.recv(ln-len(b))
        if not c: break
        b+=c
    return b
def parse(b):
    if not b or len(b)<8: return None
    return struct.unpack('>I',b[0:4])[0], struct.unpack('>H',b[4:6])[0], b[6:8], b[8:]
def asc(b): return ''.join(chr(x) if 32<=x<127 else '.' for x in b)

def go(ip):
    print(f'===== {ip} =====', flush=True)
    s=socket.create_connection((ip,2122),timeout=3); s.settimeout(0.5)
    s.sendall(frame(0,1,b'Ox',struct.pack('>HB',3000,1)))
    p=parse(recvt(s))
    sid=struct.unpack('>I',p[3][0:4])[0] if p and len(p[3])>=4 else 0
    print(f'  session=0x{sid:08x}', flush=True)
    req=2
    # by-index read sweep
    for idx in range(0,32):
        try:
            s.sendall(frame(sid,req,b'RN',struct.pack('>H',idx))); req+=1
            b=recvt(s); pr=parse(b)
            if not pr: continue
            _,_,cmd,data=pr
            isfault = (cmd==b'FA') or (data[:2]==b'FA' and len(data)<=4)
            if not isfault and data:
                ipmark = 'c0a8' in data.hex()
                print(f'  idx {idx:2d} {cmd} {"<<IP?" if ipmark else ""} {data.hex()[:96]} |{asc(data[:40])}|', flush=True)
        except socket.timeout: pass
        except Exception as e: print('  err',idx,e,flush=True)
    # by-name reads for identity
    for name in (b'DeviceType',b'FirmwareVersion',b'SerialNumber',b'OrderNumber',b'ProjectName',b'DeviceName'):
        try:
            s.sendall(frame(sid,req,b'RN',name)); req+=1
            b=recvt(s); pr=parse(b)
            if pr and pr[3] and pr[3][:2]!=b'FA':
                print(f'  name {name.decode():16s}: {pr[3].hex()[:80]} |{asc(pr[3][:40])}|', flush=True)
        except socket.timeout: pass
        except Exception as e: pass
    try: s.sendall(frame(sid,900,b'Cx')); recvt(s)
    except: pass
    s.close()

for ip in ('192.168.192.100','192.168.192.101'):
    try: go(ip)
    except Exception as e: print('FAIL',ip,e,flush=True)
print('DONE',flush=True)
