import socket, struct, json, time

IP='192.168.192.5'
def q(port, api, payload=None):
    s=socket.create_connection((IP,port),timeout=3); s.settimeout(3)
    body=b'' if payload is None else json.dumps(payload).encode()
    s.sendall(struct.pack('>BBHIH6s',0x5A,1,1,len(body),api,b'\x00'*6)+body)
    hdr=b''
    while len(hdr)<16: hdr+=s.recv(16-len(hdr))
    ln=struct.unpack('>I',hdr[4:8])[0]
    d=b''
    while len(d)<ln:
        c=s.recv(ln-len(d))
        if not c: break
        d+=c
    s.close()
    return json.loads(d.decode()) if d else {}

out={}
# pose
loc=q(19204,1004,{"return_laser":False})
out['pose']={k:loc.get(k) for k in ('x','y','angle','confidence','current_station','current_map')}
# map list
mp=q(19204,1300)
out['maps']={'current':mp.get('current_map'),'all':mp.get('maps')}
# stations
st=q(19204,1301)
out['stations']=st.get('stations',[])
# full laser (both lidars)
las=q(19204,1009,{"return_beams3D":False})
lasers=[]
for L in las.get('lasers',[]):
    di=L.get('device_info',{}); ins=L.get('install_info',{})
    beams=[{'a':b.get('angle'),'d':b.get('dist'),'v':b.get('valid'),'o':b.get('is_obstacle')} for b in L.get('beams',[])]
    lasers.append({'name':di.get('device_name'),'install':ins,'min_angle':di.get('min_angle'),
                   'max_angle':di.get('max_angle'),'max_range':di.get('max_range'),'beams':beams})
out['lasers']=lasers
out['robot']={'model':'Foil_A082','ip':IP}

json.dump(out, open('C:/Users/T-ROBO~1/AppData/Local/Temp/claude/C--WINDOWS-system32/a237a1ad-86c2-496b-9475-3eca8bfd0f60/scratchpad/viz_data.json','w'))
print('pose:', out['pose'])
print('current_map:', out['maps']['current'], '| all maps:', out['maps']['all'])
print('stations:', len(out['stations']))
for s in out['stations'][:12]: print('   ', s.get('id'), s.get('type'), round(s.get('x',0),2), round(s.get('y',0),2))
for L in lasers:
    valid=sum(1 for b in L['beams'] if b['v'])
    print(f"laser {L['name']}: {len(L['beams'])} beams, {valid} valid, install={L['install']}")
print('SAVED viz_data.json')
