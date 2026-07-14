# -*- coding: utf-8 -*-
blob = open('C:/Users/T-ROBO~1/AppData/Local/Temp/claude/C--WINDOWS-system32/a237a1ad-86c2-496b-9475-3eca8bfd0f60/scratchpad/payload.json',encoding='utf-8').read()

html = r'''<title>Foil_A082 — AMR Scan View</title>
<style>
  :root{
    --ground:#0a0e15; --panel:#0f151e; --panel2:#141c27; --edge:#1e2836;
    --grid-min:#161f2b; --grid-maj:#243040; --ink:#dbe4ef; --mute:#7d8ea3; --faint:#4a5768;
    --axX:#e5484d; --axY:#46c88a; --front:#33c7ee; --rear:#f5a83f; --robot:#eef3f9;
    --station:#b48bff; --ok:#46c88a; --warn:#f5a83f;
    --mono:ui-monospace,"Cascadia Mono","Consolas",monospace;
    --sans:"Segoe UI",system-ui,-apple-system,sans-serif;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
       display:flex;flex-direction:column;overflow:hidden}
  header{display:flex;align-items:center;gap:16px;padding:10px 18px;background:linear-gradient(180deg,#111926,#0d131c);
         border-bottom:1px solid var(--edge);flex:0 0 auto}
  header .mark{width:10px;height:10px;border-radius:50%;background:var(--ok);box-shadow:0 0 10px var(--ok);animation:pulse 2.4s infinite}
  @keyframes pulse{50%{opacity:.35}}
  @media (prefers-reduced-motion:reduce){header .mark{animation:none}}
  header h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.2px}
  header .sub{font-family:var(--mono);font-size:12px;color:var(--mute)}
  header .spacer{flex:1}
  header .chip{font-family:var(--mono);font-size:11px;color:var(--mute);border:1px solid var(--edge);
        padding:4px 9px;border-radius:5px;background:#0c121b}
  header .chip b{color:var(--ink);font-weight:600}
  main{flex:1;display:flex;min-height:0}
  .stage{position:relative;flex:1;min-width:0}
  canvas{display:block;width:100%;height:100%}
  .overlay{position:absolute;left:14px;bottom:12px;font-family:var(--mono);font-size:11px;color:var(--faint);
           pointer-events:none;line-height:1.6}
  .toolbar{position:absolute;left:14px;top:12px;display:flex;gap:6px;flex-wrap:wrap}
  .toolbar button{font-family:var(--mono);font-size:11px;color:var(--mute);background:#0d131ccc;border:1px solid var(--edge);
        padding:5px 9px;border-radius:5px;cursor:pointer;backdrop-filter:blur(3px)}
  .toolbar button:hover{color:var(--ink);border-color:#33465c}
  .toolbar button.on{color:#04121a;background:var(--front);border-color:var(--front)}
  .toolbar button.on.rear{background:var(--rear);border-color:var(--rear)}
  .toolbar button.on.st{background:var(--station);border-color:var(--station);color:#160a2a}
  .toolbar button:focus-visible{outline:2px solid #6db8ff;outline-offset:1px}
  aside{flex:0 0 288px;background:var(--panel);border-left:1px solid var(--edge);padding:16px;overflow-y:auto}
  .card{background:var(--panel2);border:1px solid var(--edge);border-radius:8px;padding:13px 14px;margin-bottom:12px}
  .card h2{margin:0 0 10px;font-size:10px;letter-spacing:1.4px;text-transform:uppercase;color:var(--mute);font-weight:700}
  .kv{display:flex;justify-content:space-between;align-items:baseline;font-family:var(--mono);font-size:12.5px;padding:3px 0}
  .kv .k{color:var(--mute)} .kv .v{color:var(--ink);font-variant-numeric:tabular-nums}
  .bar{height:6px;border-radius:3px;background:#1a2431;overflow:hidden;margin-top:7px}
  .bar > i{display:block;height:100%;background:linear-gradient(90deg,var(--ok),#7ff0b8)}
  .pill{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;
        padding:3px 8px;border-radius:20px;border:1px solid var(--edge)}
  .pill .dot{width:7px;height:7px;border-radius:50%}
  .lidar-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;font-family:var(--mono);font-size:12px}
  .lidar-row .name{display:flex;align-items:center;gap:8px}
  .swatch{width:9px;height:9px;border-radius:2px}
  .stlist{font-family:var(--mono);font-size:11.5px;color:var(--mute);line-height:1.8}
  .stlist b{color:var(--station);font-weight:600}
  .legend{font-family:var(--mono);font-size:11px;color:var(--mute);display:flex;flex-direction:column;gap:6px}
  .legend div{display:flex;align-items:center;gap:8px}
  footer{flex:0 0 auto;padding:7px 18px;background:#0b111a;border-top:1px solid var(--edge);
         font-family:var(--mono);font-size:11px;color:var(--faint);display:flex;gap:18px}
</style>

<header>
  <span class="mark" title="live session"></span>
  <div>
    <h1>Foil_A082 &nbsp;·&nbsp; AMR Scan View</h1>
    <div class="sub">SEER SRC @ 192.168.192.5 &nbsp;|&nbsp; map: <span id="mapname"></span></div>
  </div>
  <span class="spacer"></span>
  <span class="chip">pose&nbsp; <b id="cpose"></b></span>
  <span class="chip">loc&nbsp; <b id="cconf"></b></span>
  <span class="chip" id="cpts"></span>
</header>

<main>
  <div class="stage">
    <canvas id="c"></canvas>
    <div class="toolbar">
      <button id="tFront" class="on">FRONT LiDAR</button>
      <button id="tRear" class="on rear">REAR LiDAR</button>
      <button id="tSt" class="on st">STATIONS</button>
      <button id="tGrid">GRID</button>
      <button id="tReset">RECENTER</button>
    </div>
    <div class="overlay" id="ov"></div>
  </div>

  <aside>
    <div class="card">
      <h2>Robot Pose</h2>
      <div class="kv"><span class="k">x</span><span class="v" id="px"></span></div>
      <div class="kv"><span class="k">y</span><span class="v" id="py"></span></div>
      <div class="kv"><span class="k">θ (heading)</span><span class="v" id="pth"></span></div>
      <div class="kv"><span class="k">localization</span><span class="v" id="pcf"></span></div>
      <div class="bar"><i id="cfbar"></i></div>
    </div>

    <div class="card">
      <h2>LiDAR Health</h2>
      <div class="lidar-row"><span class="name"><span class="swatch" style="background:var(--front)"></span>FrontLiDAR</span><span id="lf"></span></div>
      <div class="lidar-row"><span class="name"><span class="swatch" style="background:var(--rear)"></span>RearLiDAR</span><span id="lr"></span></div>
      <div style="margin-top:8px"><span class="pill"><span class="dot" style="background:var(--ok)"></span>both returning valid scan data</span></div>
    </div>

    <div class="card">
      <h2>Stations · Current Map</h2>
      <div class="stlist" id="stlist"></div>
    </div>

    <div class="card">
      <h2>Legend</h2>
      <div class="legend">
        <div><span class="swatch" style="background:var(--front)"></span> Front scan point</div>
        <div><span class="swatch" style="background:var(--rear)"></span> Rear scan point</div>
        <div><span class="swatch" style="background:var(--station);border-radius:50%"></span> Location mark (LM)</div>
        <div><span class="swatch" style="background:var(--axX)"></span> +X world axis &nbsp;<span class="swatch" style="background:var(--axY)"></span> +Y</div>
      </div>
    </div>
  </aside>
</main>

<footer>
  <span>drag to pan · scroll to zoom</span>
  <span id="fscale"></span>
  <span>snapshot · SEER API 1004/1009/1300/1301</span>
  <span style="margin-left:auto">frame: world · grid 1 m</span>
</footer>

<script>
const DATA = __PAYLOAD__;
const cv=document.getElementById('c'), ctx=cv.getContext('2d');
let scale=null, ox=0, oy=0, dragging=false, lx=0, ly=0;
const show={front:true,rear:true,st:true,grid:true};

// fit view to all content initially
function bounds(){
  let xs=[DATA.pose.x], ys=[DATA.pose.y];
  DATA.stations.forEach(s=>{xs.push(s.x);ys.push(s.y)});
  DATA.lasers.forEach(L=>L.pts.forEach(p=>{xs.push(p[0]);ys.push(p[1])}));
  return {minx:Math.min(...xs),maxx:Math.max(...xs),miny:Math.min(...ys),maxy:Math.max(...ys)};
}
function resize(){
  const r=cv.parentElement.getBoundingClientRect(), dpr=devicePixelRatio||1;
  cv.width=r.width*dpr; cv.height=r.height*dpr; ctx.setTransform(dpr,0,0,dpr,0,0);
  cv._w=r.width; cv._h=r.height;
  if(scale===null) fit();
  draw();
}
function fit(){
  const b=bounds(), pad=1.4;
  const w=(b.maxx-b.minx)||1, h=(b.maxy-b.miny)||1;
  scale=Math.min(cv._w/(w*pad), cv._h/(h*pad));
  const cx=(b.minx+b.maxx)/2, cy=(b.miny+b.maxy)/2;
  ox=cv._w/2 - cx*scale; oy=cv._h/2 + cy*scale;
}
// world -> screen (Y up)
function sx(x){return x*scale+ox}
function sy(y){return -y*scale+oy}

function draw(){
  const W=cv._w,H=cv._h;
  ctx.fillStyle='#0a0e15'; ctx.fillRect(0,0,W,H);
  if(show.grid) drawGrid(W,H);
  drawAxes();
  if(show.st) drawStationsPoly();
  DATA.lasers.forEach((L,i)=>{
    if(i===0&&!show.front) return; if(i===1&&!show.rear) return;
    ctx.fillStyle=i===0?'#33c7ee':'#f5a83f';
    ctx.globalAlpha=.85;
    L.pts.forEach(p=>{ ctx.fillRect(sx(p[0])-1.1, sy(p[1])-1.1, 2.2, 2.2); });
    ctx.globalAlpha=1;
  });
  if(show.st) drawStations();
  drawRobot();
  // scale bar
  document.getElementById('fscale').textContent='zoom '+scale.toFixed(1)+' px/m';
}
function niceStep(){
  const target=90/scale; const pw=Math.pow(10,Math.floor(Math.log10(target)));
  const c=[1,2,5,10]; for(const m of c){ if(pw*m>=target) return pw*m; } return pw*10;
}
function drawGrid(W,H){
  const step=niceStep();
  const x0=Math.floor((-ox/scale)/step)*step, x1=(W-ox)/scale;
  const y0=Math.floor((oy-H)/scale/step)*step, y1=oy/scale;
  ctx.lineWidth=1;
  for(let x=x0;x<=x1;x+=step){ ctx.strokeStyle=Math.abs(x)<1e-6?'#243040':'#161f2b';
    ctx.beginPath();ctx.moveTo(sx(x),0);ctx.lineTo(sx(x),H);ctx.stroke(); }
  for(let y=y0;y<=y1;y+=step){ ctx.strokeStyle=Math.abs(y)<1e-6?'#243040':'#161f2b';
    ctx.beginPath();ctx.moveTo(0,sy(y));ctx.lineTo(W,sy(y));ctx.stroke(); }
}
function drawAxes(){
  const o=[sx(0),sy(0)], L=1.4*scale;
  ctx.lineWidth=2;
  ctx.strokeStyle='#e5484d'; ctx.beginPath();ctx.moveTo(o[0],o[1]);ctx.lineTo(o[0]+L,o[1]);ctx.stroke();
  ctx.strokeStyle='#46c88a'; ctx.beginPath();ctx.moveTo(o[0],o[1]);ctx.lineTo(o[0],o[1]-L);ctx.stroke();
}
function drawStationsPoly(){
  const s=DATA.stations; if(s.length<2) return;
  ctx.strokeStyle='rgba(180,139,255,.28)'; ctx.lineWidth=1.5; ctx.setLineDash([5,5]);
  ctx.beginPath(); ctx.moveTo(sx(s[0].x),sy(s[0].y));
  for(let i=1;i<s.length;i++) ctx.lineTo(sx(s[i].x),sy(s[i].y));
  ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);
}
function drawStations(){
  ctx.font='11px ui-monospace,Consolas,monospace';
  DATA.stations.forEach(s=>{
    const X=sx(s.x),Y=sy(s.y);
    ctx.fillStyle='#b48bff';
    ctx.beginPath(); ctx.moveTo(X,Y-6);ctx.lineTo(X+6,Y);ctx.lineTo(X,Y+6);ctx.lineTo(X-6,Y);ctx.closePath(); ctx.fill();
    ctx.fillStyle='#d9c9ff'; ctx.fillText(s.id, X+9, Y-6);
  });
}
function drawRobot(){
  const X=sx(DATA.pose.x), Y=sy(DATA.pose.y), a=-DATA.pose.angle;
  const Lm=1.2*scale, Wm=0.8*scale; // footprint approx (m)
  ctx.save(); ctx.translate(X,Y); ctx.rotate(a);
  ctx.strokeStyle='#eef3f9'; ctx.lineWidth=2; ctx.fillStyle='rgba(238,243,249,.10)';
  ctx.beginPath(); ctx.rect(-Lm/2,-Wm/2,Lm,Wm); ctx.fill(); ctx.stroke();
  // heading arrow
  ctx.strokeStyle='#e5484d'; ctx.fillStyle='#e5484d'; ctx.lineWidth=2.5;
  ctx.beginPath(); ctx.moveTo(0,0); ctx.lineTo(Lm*0.62,0); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(Lm*0.62,0);ctx.lineTo(Lm*0.62-8,-5);ctx.lineTo(Lm*0.62-8,5);ctx.closePath();ctx.fill();
  ctx.restore();
  ctx.fillStyle='#8aa0b6'; ctx.font='11px ui-monospace,Consolas,monospace';
  ctx.fillText('base_link', X+8, Y+16);
}

// interaction
cv.addEventListener('mousedown',e=>{dragging=true;lx=e.clientX;ly=e.clientY});
addEventListener('mouseup',()=>dragging=false);
addEventListener('mousemove',e=>{ if(!dragging)return; ox+=e.clientX-lx; oy+=e.clientY-ly; lx=e.clientX;ly=e.clientY; draw(); });
cv.addEventListener('wheel',e=>{e.preventDefault();
  const f=e.deltaY<0?1.12:1/1.12; const mx=e.offsetX,my=e.offsetY;
  ox=mx-(mx-ox)*f; oy=my-(my-oy)*f; scale*=f; draw();
},{passive:false});
function btn(id,key,cls){const b=document.getElementById(id);b.onclick=()=>{show[key]=!show[key];
  b.classList.toggle('on');draw();};}
btn('tFront','front');btn('tRear','rear');btn('tSt','st');
document.getElementById('tGrid').onclick=function(){show.grid=!show.grid;this.classList.toggle('on');draw();};
document.getElementById('tReset').onclick=()=>{fit();draw();};

// populate panels
const P=DATA.pose;
document.getElementById('mapname').textContent=DATA.map+'  ('+DATA.nmaps+' stored)';
document.getElementById('cpose').textContent=P.x.toFixed(2)+', '+P.y.toFixed(2);
document.getElementById('cconf').textContent=(P.confidence*100).toFixed(1)+'%';
document.getElementById('px').textContent=P.x.toFixed(4)+' m';
document.getElementById('py').textContent=P.y.toFixed(4)+' m';
document.getElementById('pth').textContent=(P.angle*57.2958).toFixed(2)+'°  ('+P.angle.toFixed(4)+' rad)';
document.getElementById('pcf').textContent=(P.confidence*100).toFixed(2)+'%';
document.getElementById('cfbar').style.width=(P.confidence*100)+'%';
const F=DATA.lasers[0],R=DATA.lasers[1];
document.getElementById('lf').textContent=F.nvalid+'/'+F.nbeams+' valid';
document.getElementById('lr').textContent=R.nvalid+'/'+R.nbeams+' valid';
document.getElementById('cpts').innerHTML='pts&nbsp; <b>'+(F.nvalid+R.nvalid)+'</b>';
document.getElementById('stlist').innerHTML=DATA.stations.map(s=>'<b>'+s.id+'</b> '+s.type+' &nbsp;('+s.x.toFixed(2)+', '+s.y.toFixed(2)+')').join('<br>');
document.getElementById('ov').innerHTML='world frame · Y up<br>origin = map (0,0)<br>robot footprint ≈ 1.2 × 0.8 m (approx)';

addEventListener('resize',resize); resize();
</script>'''

html = html.replace('__PAYLOAD__', blob)
open('C:/Users/T-ROBO~1/AppData/Local/Temp/claude/C--WINDOWS-system32/a237a1ad-86c2-496b-9475-3eca8bfd0f60/scratchpad/amr_view.html','w',encoding='utf-8').write(html)
print('written', len(html), 'bytes')
