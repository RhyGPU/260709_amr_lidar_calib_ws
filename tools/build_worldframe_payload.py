# -*- coding: utf-8 -*-
import json, math

d = json.load(open('C:/Users/T-ROBO~1/AppData/Local/Temp/claude/C--WINDOWS-system32/a237a1ad-86c2-496b-9475-3eca8bfd0f60/scratchpad/viz_data.json'))
pose = d['pose']; px, py, pa = pose['x'], pose['y'], pose['angle']

def to_world(L):
    ins = L['install']; ix, iy, iyaw = ins['x'], ins['y'], math.radians(ins['yaw'])
    pts = []
    for b in L['beams']:
        if not b['v'] or b['d'] is None: continue
        la = math.radians(b['a']); lx = b['d']*math.cos(la); ly = b['d']*math.sin(la)
        bx = ix + lx*math.cos(iyaw) - ly*math.sin(iyaw)
        by = iy + lx*math.sin(iyaw) + ly*math.cos(iyaw)
        wx = px + bx*math.cos(pa) - by*math.sin(pa)
        wy = py + bx*math.sin(pa) + by*math.cos(pa)
        pts.append([round(wx,3), round(wy,3), 1 if b.get('o') else 0])
    return pts

lasers = []
for L in d['lasers']:
    lasers.append({'name': L['name'], 'pts': to_world(L),
                   'nbeams': len(L['beams']), 'nvalid': sum(1 for b in L['beams'] if b['v'])})

payload = {
    'robot': {'model': d['robot']['model'], 'ip': d['robot']['ip']},
    'pose': {'x': round(px,4), 'y': round(py,4), 'angle': round(pa,4), 'confidence': pose['confidence']},
    'map': d['maps']['current'], 'nmaps': len(d['maps']['all']),
    'stations': [{'id': s['id'], 'type': s['type'], 'x': round(s['x'],3), 'y': round(s['y'],3), 'r': s.get('r',0)} for s in d['stations']],
    'lasers': lasers,
}
blob = json.dumps(payload, separators=(',',':'))
print('front pts', len(lasers[0]['pts']), 'rear pts', len(lasers[1]['pts']), 'blob KB', round(len(blob)/1024,1))
open('C:/Users/T-ROBO~1/AppData/Local/Temp/claude/C--WINDOWS-system32/a237a1ad-86c2-496b-9475-3eca8bfd0f60/scratchpad/payload.json','w').write(blob)
