"""Reel no estilo "palco": uma plataforma flutuante sobre um fundo low poly, o mascote (cubo azul, gravata âmbar) e cartões
que entram a cada cena, com legenda em karaokê. Tudo é desenhado por código no Chromium, quadro a quadro.

O roteiro é o mesmo do Reel de gancho (gancho, palavra de destaque, cenas com rótulo/antes/texto/apoio e chamada final):
- o gancho vira o título grande no topo, com a palavra de destaque em âmbar;
- cada cena vira um cartão (esquerda e direita, alternando); o rótulo define a cor do cabeçalho (vermelho = erro/mito,
  azul = certo/ação, âmbar = explicação) e a reação do mascote (balança a cabeça, comemora, aponta, pensa);
- cena com "antes": o cartão mostra a versão fraca, risca e troca pela melhor;
- as palavras da cena aparecem em karaokê na parte de baixo; a chamada final fecha o vídeo.
Se algo falhar aqui, o chamador cai no Reel de gancho (reel_gancho.py), que é mais simples.
"""
import hashlib
import html
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import ASSETS
from .render_v2 import clean

FPS = 24
MAX_TOTAL = 32.0     # segundos: acima disso o robô tira o texto de apoio e comprime as cenas
READ = 4.0           # palavras por segundo na leitura
CAPS = re.compile(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ]{4,})\b")
REACOES = {"no": {"MITO", "O ERRO", "EVITE", "POR QUE ATRAPALHA"},
           "celebrate": {"VERDADE", "CORRIJA ASSIM", "DEPOIS", "HOJE", "ANTES / DEPOIS"},
           "point": {"FAÇA ASSIM", "FAÇA ISSO", "NA PRÁTICA", "COMO RESPONDER"},
           "think": {"POR QUÊ", "O QUE ELE QUER SABER", "A VIRADA", "RESPOSTA CURTA"}}


def _t(x):
    return re.sub(r"\s+", " ", clean(x or "")).strip()


def _w(x):
    return len(_t(x).split())


def _reacao(rotulo, tem_antes):
    if tem_antes:
        return "celebrate"
    if re.fullmatch(r"\d", rotulo):
        return "point"
    for nome, conj in REACOES.items():
        if rotulo in conj:
            return nome
    return "nod"


def _hook_html(gancho, destaque):
    s = html.escape(gancho)
    d = _t(destaque).strip(".,!?:;")
    if d:
        s = re.sub(re.escape(html.escape(d)), lambda m: f'<span class="u">{m.group(0)}</span>', s, count=1, flags=re.I)
    return s


def _palavras(texto, ini, fim):
    """Tempo de cada palavra em karaokê: distribuído pelo número de letras entre ini e fim."""
    ws = _t(texto).split()
    if not ws:
        return []
    pesos = [max(2, len(re.sub(r"\W", "", w))) + 1 for w in ws]
    total, t, out = float(sum(pesos)), ini, []
    for w, p in zip(ws, pesos):
        d = (fim - ini) * p / total
        out.append({"w": w, "t0": round(t, 3), "t1": round(t + d, 3), "hl": bool(CAPS.fullmatch(re.sub(r"[.,!?:;]+$", "", w)))})
        t += d
    return out


def _duracoes(cenas, chamada, gancho, com_apoio):
    hook = max(2.2, round(_w(gancho) / 3.8 + 0.9, 2))
    beats = []
    for c in cenas:
        antes, texto, apoio = _t(c.get("antes")), _t(c.get("texto")), _t(c.get("apoio")) if com_apoio else ""
        if antes:
            swap = max(1.5, round(_w(antes) / READ + 1.1, 2))
            beats.append((swap + max(1.9, round(_w(texto) / READ + 0.9, 2)), swap))
        else:
            beats.append((max(2.4, round(_w(texto) / READ + 0.9 + (_w(apoio) / 5.0 if apoio else 0), 2)), 0.0))
    cta = max(2.6, round(_w(chamada) / 3.6 + 1.0, 2))
    return hook, beats, cta


def montar_dados(roteiro, mostrar_link=False):
    gancho, chamada = _t(roteiro["gancho"]), _t(roteiro["chamada"])
    cenas = [c for c in roteiro["cenas"] if _t(c.get("texto"))]
    com_apoio = True
    hook, beats, cta = _duracoes(cenas, chamada, gancho, com_apoio)
    if hook + sum(d for d, _ in beats) + cta > MAX_TOTAL:
        com_apoio = False
        hook, beats, cta = _duracoes(cenas, chamada, gancho, com_apoio)
    fator = 1.0
    soma = sum(d for d, _ in beats)
    if hook + soma + cta > MAX_TOTAL:
        fator = max(0.75, (MAX_TOTAL - hook - cta) / soma)
    out_beats, caps, t = [], [], hook
    for i, (c, (dur, swap)) in enumerate(zip(cenas, beats)):
        dur, swap = round(dur * fator, 3), round(swap * fator, 3)
        antes, texto = _t(c.get("antes")), _t(c.get("texto"))
        apoio = _t(c.get("apoio")) if com_apoio else ""
        rot = _t(c.get("rotulo")).upper()
        out_beats.append({"t0": round(t, 3), "t1": round(t + dur, 3), "rotulo": rot, "antes": antes, "texto": texto, "apoio": apoio,
                          "side": -1 if i % 2 == 0 else 1, "react": _reacao(rot, bool(antes)), "swap": swap})
        ini = t + (swap + 0.2 if antes else 0.3)
        fim = t + dur - (0.2 if antes else dur * 0.15)
        caps.append({"ini": round(ini - 0.05, 3), "fim": round(t + dur, 3), "words": _palavras(texto, ini, max(fim, ini + 0.8))})
        t += dur
    out_cta = {"t0": round(t, 3), "t1": round(t + cta, 3)}
    caps.append({"ini": round(t + 0.1, 3), "fim": out_cta["t1"], "words": _palavras(chamada, t + 0.2, t + cta - 0.3)})
    return {"hook": {"html": _hook_html(gancho, roteiro.get("destaque", "")), "dur": hook}, "beats": out_beats, "cta": out_cta,
            "caps": caps, "total": round(t + cta, 3), "link": bool(mostrar_link)}


TEMPLATE = r'''<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:P;src:url("file://__FONTDIR__/Poppins-Bold.ttf");font-weight:700}
@font-face{font-family:P;src:url("file://__FONTDIR__/Poppins-Medium.ttf");font-weight:500}
html,body{margin:0;background:#0A0E1A;overflow:hidden}
#c{position:absolute;left:0;top:0}
#hl{position:absolute;left:84px;right:84px;top:150px;font-family:P;font-weight:700;font-size:96px;line-height:1.06;letter-spacing:-2px;color:#F5F6FA;text-shadow:0 6px 24px rgba(0,0,0,.35)}
#hl .u{color:#E8A33D}
#bar{position:absolute;left:84px;top:140px;height:10px;width:0;background:#E8A33D;border-radius:5px}
#kar{position:absolute;left:60px;right:60px;top:1650px;text-align:center;font-family:P;font-weight:700;font-size:78px;line-height:1.12;letter-spacing:-1px;color:#F5F6FA;text-shadow:0 6px 22px rgba(0,0,0,.55)}
#kar span{display:inline-block;margin:0 12px;opacity:0;transform:translateY(16px)}
#kar span.on{color:#E8A33D}
</style></head><body>
<canvas id="c" width="1080" height="1920"></canvas>
<div id="bar"></div><div id="hl"></div><div id="kar"></div>
<script>
const W=1080,H=1920,ctx=document.getElementById('c').getContext('2d');
const D=Math.PI/180,clamp=(x,a=0,b=1)=>Math.min(b,Math.max(a,x)),sm=x=>{x=clamp(x);return x*x*(3-2*x)};
const eo=x=>1-Math.pow(1-clamp(x),3),eb=x=>{x=clamp(x);const c1=1.70158,c3=c1+1;return 1+c3*Math.pow(x-1,3)+c1*Math.pow(x-1,2)};
const LERP=(a,b,k)=>a+(b-a)*k;
const rgb=(c,k=1)=>`rgb(${Math.min(255,c[0]*k)|0},${Math.min(255,c[1]*k)|0},${Math.min(255,c[2]*k)|0})`,mixc=(a,b,k)=>a.map((v,i)=>v+(b[i]-v)*k);
function rng(s){return function(){s|=0;s=s+0x6D2B79F5|0;let t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
const add=(a,b)=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]],sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]],mul=(a,k)=>[a[0]*k,a[1]*k,a[2]*k],dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],nrm=a=>{const l=Math.hypot(...a)||1;return[a[0]/l,a[1]/l,a[2]/l]};
const rx=(v,a)=>{const c=Math.cos(a),s=Math.sin(a);return[v[0],v[1]*c-v[2]*s,v[1]*s+v[2]*c]},ry=(v,a)=>{const c=Math.cos(a),s=Math.sin(a);return[v[0]*c+v[2]*s,v[1],-v[0]*s+v[2]*c]},rz=(v,a)=>{const c=Math.cos(a),s=Math.sin(a);return[v[0]*c-v[1]*s,v[0]*s+v[1]*c,v[2]]};
// ---- câmera (órbita lenta)
const FOV=40*D,F=(H/2)/Math.tan(FOV/2);let CP,CF,CR,CU;const CT=[0,2.6,0];
function camera(t){const a=Math.sin(t*.4)*.16,r=24-1.5*eo(t/1.5);CP=[Math.sin(a)*r,10.5,Math.cos(a)*r];CF=nrm(sub(CT,CP));CR=nrm(cross(CF,[0,1,0]));CU=cross(CR,CF)}
const view=p=>{const d=sub(p,CP);return[dot(d,CR),dot(d,CU),dot(d,CF)]},scr=v=>[W/2+v[0]/v[2]*F,H/2-v[1]/v[2]*F],P2=p=>scr(view(p));
const LUZ=nrm([-.35,.9,.55]);
// ---- caixas
const FACES=[[1,5,7,3],[0,2,6,4],[2,3,7,6],[0,4,5,1],[4,6,7,5],[0,1,3,2]];
let lista=[];
function caixa(c,h,tf,col,direto){const cs=[];for(let i=0;i<8;i++)cs.push(tf([c[0]+(i&1?h[0]:-h[0]),c[1]+(i&2?h[1]:-h[1]),c[2]+(i&4?h[2]:-h[2])]));
  const ctr=tf(c),out=[];
  for(const f of FACES){const pts=f.map(i=>cs[i]);const cen=mul(add(add(pts[0],pts[1]),add(pts[2],pts[3])),.25);const n=nrm(sub(cen,ctr));
    if(dot(n,sub(CP,cen))<=0)continue;out.push({pts,n,z:view(cen)[2],col,sh:.62+.38*Math.max(0,dot(n,LUZ))})}
  if(direto)return out;lista.push(...out);return out}
function decal(quad,n,z,col,extra){lista.push({pts:quad,n,z:z-.06,col,dec:true,...(extra||{})})}
function Tparte(pos,yaw,s,piv,rot){return p=>{let q=p;if(piv){q=add(piv,ry(rz(rx(sub(q,piv),rot[0]),rot[1]),rot[2]||0))}return add(pos,ry(mul(q,s),yaw))}}
const poly=(p,fill,stroke)=>{ctx.fillStyle=fill;ctx.beginPath();ctx.moveTo(...p[0]);for(let i=1;i<p.length;i++)ctx.lineTo(...p[i]);ctx.closePath();ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.stroke()}};
// ---- fundo: malha low poly + cristais
const C0=[10,14,26],C1=[11,30,61],C2=[47,111,237],AM=[232,163,61];
const COLS=8,ROWS=14,R=rng(SEED),PM={};for(let j=-1;j<=ROWS+1;j++){PM[j]={};for(let i=-1;i<=COLS+1;i++)PM[j][i]={x:i*W/COLS+(R()-.5)*95,y:j*H/ROWS+(R()-.5)*95,a:R()*6.28,b:R()*6.28}}
const TJ=[];for(let k=0;k<(COLS+3)*(ROWS+3)*2;k++)TJ.push(R());
function fundo(t){ctx.fillStyle=rgb(C0);ctx.fillRect(0,0,W,H);let n=0;
  for(let j=-1;j<=ROWS;j++)for(let i=-1;i<=COLS;i++){const q=(i,j)=>{const p=PM[j][i];return[p.x+Math.sin(t*.7+p.a)*14,p.y+Math.cos(t*.6+p.b)*14]};
    const a=q(i,j),b=q(i+1,j),c=q(i,j+1),d=q(i+1,j+1),tris=((i+j)%2)?[[a,b,d],[a,d,c]]:[[a,b,c],[b,d,c]];
    for(const T of tris){const cy=(T[0][1]+T[1][1]+T[2][1])/3/H;let k=clamp(.1+cy*.8);let col=mixc(mixc(C0,C1,clamp(k*1.7)),C2,Math.max(0,k-.6)*.7);
      col=mixc(col,[255,255,255],(TJ[n]-.5)*.07+(Math.sin(t*1.3+TJ[n]*40)*.5+.5)*.035);ctx.fillStyle=ctx.strokeStyle=rgb(col);ctx.lineWidth=1.2;
      ctx.beginPath();ctx.moveTo(...T[0]);ctx.lineTo(...T[1]);ctx.lineTo(...T[2]);ctx.closePath();ctx.fill();ctx.stroke();n++}}}
// ---- plataforma flutuante
function plataforma(y0,k){const tf=p=>add([0,y0,0],p),fs=caixa([0,-.55,0],[4.3,.55,3.4],tf,[70,110,200],true);
  fs.sort((a,b)=>b.z-a.z);for(const f of fs){const p=f.pts.map(P2);const top=f.n[1]>.5;
    if(top){const g=ctx.createLinearGradient(0,p[0][1],0,p[2][1]);g.addColorStop(0,'#e8edf9');g.addColorStop(1,'#c4d0ee');poly(p,g)}else poly(p,rgb([40,78,168],f.sh*.85),rgb([40,78,168],f.sh*.85))}
  // grade na face de cima
  ctx.strokeStyle='rgba(47,111,237,.22)';ctx.lineWidth=2;
  for(let i=-4;i<=4;i++){ctx.beginPath();const a=P2(tf([i*1.0,0.01,-3.4])),b=P2(tf([i*1.0,0.01,3.4]));ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}
  for(let j=-3;j<=3;j++){ctx.beginPath();const a=P2(tf([-4.3,0.01,j*1.0])),b=P2(tf([4.3,0.01,j*1.0]));ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}
  // faixa âmbar na borda frontal
  const e=[[-4.3,0,3.4],[4.3,0,3.4],[4.3,-.16,3.4],[-4.3,-.16,3.4]].map(v=>P2(tf(v)));poly(e,'#E8A33D');
}
function sombra(x,z,rx_,rz_,a,y=0.02){const pts=[];for(let i=0;i<28;i++){const t=i/28*6.283;pts.push(P2([x+Math.cos(t)*rx_,y,z+Math.sin(t)*rz_]))}
  ctx.fillStyle=`rgba(11,30,61,${a})`;ctx.beginPath();ctx.moveTo(...pts[0]);for(const p of pts)ctx.lineTo(...p);ctx.closePath();ctx.fill()}
// ---- mascote (o mesmo avatar: cubo azul, gravata âmbar, só os olhos)
const AZUL=[47,111,237],AZULc=[62,128,248],AZULp=[24,56,128];
function cubinho(o){const {pos,yaw,s=1,anim}=o,{bobY=0,armL=[0,0],armR=[0,0],legL=0,legR=0,tilt=0,shake=0}=anim;
  const base=(piv,rot)=>Tparte([pos[0],pos[1]+bobY,pos[2]],yaw,s,piv,rot);
  caixa([-.3,.5,0],[.2,.5,.2],base([-.3,1,0],[legL,0]),AZULp);caixa([.3,.5,0],[.2,.5,.2],base([.3,1,0],[legR,0]),AZULp);
  caixa([-.78,1.4,0],[.16,.5,.16],base([-.78,1.9,0],armL),AZUL.map(v=>v*.92));caixa([.78,1.4,0],[.16,.5,.16],base([.78,1.9,0],armR),AZUL.map(v=>v*.92));
  caixa([0,1.35,0],[.58,.62,.42],base(null,null),AZUL);
  const tcab=Tparte([pos[0],pos[1]+bobY,pos[2]],yaw,s,[0,2.1,0],[0,tilt,shake]);caixa([0,2.95,0],[.85,.85,.85],tcab,AZULc);
  const nF=ry([0,0,1],yaw),zc=view(Tparte(pos,yaw,s,null,null)([0,2.95,.85]))[2],vis=dot(nF,sub(CP,add(pos,ry(mul([0,2.95,.85],s),yaw))))>0;
  if(vis){const q=(x0,y0,x1,y1)=>[[x0,y1],[x1,y1],[x1,y0],[x0,y0]].map(p=>tcab([p[0],p[1]+2.95,.86]));
    decal(q(-.5,-.05,-.28,.34),nF,zc,[14,16,28]);decal(q(.28,-.05,.5,.34),nF,zc,[14,16,28]);
    const T=base(null,null);decal([[-.14,1.05],[.14,1.05],[.1,1.9],[-.1,1.9]].map(p=>T([p[0],p[1],.43])),nF,zc+.8,AM)}}
// ---- cartões flutuantes (placa fina com textura)
function cartao(pos,yaw,tilt,sc,tw,th,fn){const tf=p=>add(pos,ry(rz(mul(p,sc),tilt),yaw)),n=ry(rz([0,0,1],tilt),yaw);
  caixa([0,0,0],[1.5,1.9,.07],tf,[245,247,252]);
  const q=[[-1.4,1.8],[1.4,1.8],[-1.4,-1.8]].map(p=>tf([p[0],p[1],.075])),cen=tf([0,0,.08]);
  if(dot(n,sub(CP,cen))>0)decal([q[0],q[1],tf([1.4,-1.8,.075]),q[2]],n,view(cen)[2]-.02,[255,255,255],{q,tex:true,tw,th,fn})}
function desenha(){lista.sort((a,b)=>b.z-a.z);
  for(const f of lista){if(f.tex){const [p0,p1,p2]=f.q.map(P2);ctx.save();ctx.transform((p1[0]-p0[0])/f.tw,(p1[1]-p0[1])/f.tw,(p2[0]-p0[0])/f.th,(p2[1]-p0[1])/f.th,p0[0],p0[1]);f.fn(ctx);ctx.restore();continue}
    const p=f.pts.map(P2);ctx.fillStyle=rgb(f.col,f.dec?1:f.sh);ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=1.2;ctx.beginPath();ctx.moveTo(...p[0]);for(let i=1;i<4;i++)ctx.lineTo(...p[i]);ctx.closePath();ctx.fill();ctx.stroke()}
  lista=[]}
// ================= guiado por dados =================
const DATA=__DATA__;
const hl=document.getElementById('hl'),bar=document.getElementById('bar'),kar=document.getElementById('kar');
hl.innerHTML=DATA.hook.html;
(function ajusta(){let fs=96;hl.style.fontSize=fs+'px';while(hl.scrollHeight>372&&fs>56){fs-=4;hl.style.fontSize=fs+'px'}})();
const NEG=['MITO','O ERRO','EVITE','POR QUE ATRAPALHA','ANTES'],POS=['VERDADE','CORRIJA ASSIM','FAÇA ASSIM','FAÇA ISSO','HOJE','NA PRÁTICA','DEPOIS','COMO RESPONDER'];
function tipo(r){r=(r||'').toUpperCase();if(/^\d$/.test(r))return'pos';if(NEG.includes(r))return'neg';if(POS.includes(r))return'pos';return'neu'}
function quebra(c,txt,maxW){const ws=String(txt).split(/\s+/),ls=[];let cur='';for(const w of ws){const t=cur?cur+' '+w:w;if(c.measureText(t).width>maxW&&cur){ls.push(cur);cur=w}else cur=t}if(cur)ls.push(cur);return ls}
function ajustaFonte(c,txt,maxW,maxLinhas,fs0,fsMin,peso){let fs=fs0,ls;do{c.font=`${peso} ${fs}px P`;ls=quebra(c,txt,maxW);if(ls.length<=maxLinhas&&ls.every(l=>c.measureText(l).width<=maxW))break;fs-=2}while(fs>fsMin);return{fs,ls}}
const TW=420,TH=520;
function icone(c,kind,x,y){c.save();c.strokeStyle='#fff';c.fillStyle='#fff';c.lineWidth=11;c.lineCap='round';c.lineJoin='round';
  if(kind==='neg'){c.beginPath();c.moveTo(x-24,y-24);c.lineTo(x+24,y+24);c.moveTo(x+24,y-24);c.lineTo(x-24,y+24);c.stroke()}
  else if(kind==='pos'){c.beginPath();c.moveTo(x-28,y+2);c.lineTo(x-8,y+24);c.lineTo(x+28,y-22);c.stroke()}
  else{c.font='700 62px P';c.textAlign='center';c.fillText('?',x,y+22);c.textAlign='left'}c.restore()}
function desenhaCartao(b,tl){return function(c){
  c.fillStyle='#fff';c.fillRect(0,0,TW,TH);
  let kind=tipo(b.rotulo),head=b.rotulo,body=b.texto,sub=b.apoio,strike=0;
  if(b.antes){ if(tl<b.swap){kind='neg';head='ANTES';body=b.antes;sub='';strike=clamp((tl-(b.swap-.75))/.5)}else{kind='pos';head='DEPOIS'}}
  const col=kind==='neg'?(b.antes?'#7b86a3':'#E5645C'):kind==='pos'?'#2F6FED':'#E8A33D';
  c.fillStyle=col;c.fillRect(0,0,TW,120);
  c.fillStyle='#fff';c.textAlign='left';let hf=/^\d$/.test(head)?84:54;c.font=`700 ${hf}px P`;while(c.measureText(head).width>TW-150&&hf>26){hf-=2;c.font=`700 ${hf}px P`}
  c.fillText(head,30,60+hf*.36);icone(c,kind,TW-62,60);
  const {fs,ls}=ajustaFonte(c,body,TW-60,4,52,34,700);c.font=`700 ${fs}px P`;c.fillStyle='#0B1E3D';
  ls.forEach((s,i)=>c.fillText(s,30,196+i*(fs*1.28)));
  if(strike>0){const y=196+(ls.length-1)*(fs*1.28)/2-fs*.3;c.strokeStyle='#E5645C';c.lineWidth=10;c.lineCap='round';c.beginPath();c.moveTo(24,y);c.lineTo(24+(TW-48)*strike,y);c.stroke()}
  if(sub){c.font='500 32px P';c.fillStyle='#5a6785';const l2=quebra(c,sub,TW-60).slice(0,2);l2.forEach((s,i)=>c.fillText(s,30,196+ls.length*(fs*1.28)+14+i*40))}
  if(!sub){c.fillStyle='#E8A33D';c.fillRect(30,TH-52,150,12)}}}
// legendas (karaokê)
const CAPS=DATA.caps;CAPS.forEach(f=>{f.el=f.words.map(w=>{const e=document.createElement('span');e.textContent=w.w;if(w.hl)e.dataset.hl='1';kar.appendChild(e);return e})});
// reações do mascote por tipo de cena
function reacao(b,t){let u=t-b.t0,R=b.react;const o={armL:[0,0],armR:[0,0],shake:0,tilt:0,jump:0,dip:0};
  if(b.antes){if(u<b.swap){if(u>.3&&u<1.6)o.shake=Math.sin((u-.3)*11)*.4*Math.min(1,(1.6-u)*2);return o}u-=b.swap;R='celebrate'}
  if(R==='no'&&u<1.7){o.shake=Math.sin(u*11)*.45*Math.min(1,(1.7-u)*2)}
  else if(R==='celebrate'&&u>.25&&u<2.4){const kk=Math.min(1,(u-.25)*3);o.armL=[-3.1*kk,.95*kk];o.armR=[-3.1*kk,-.95*kk];o.jump=Math.abs(Math.sin((u-.25)*4.2))*.9}
  else if(R==='point'&&u>.2&&u<2.2){const kk=Math.min(1,(u-.2)*3);if(b.side<0)o.armL=[-3.1*kk,.95*kk];else o.armR=[-3.1*kk,-.95*kk]}
  else if(R==='think'&&u>.2&&u<2.4){const kk=sm((u-.2)/.4);o.tilt=.22*kk;o.armR=[-1.7*kk,-.15*kk]}
  else if(u<1.0){o.dip=-.1*Math.abs(Math.sin(u*8))}
  return o}
function render(t){camera(t);ctx.clearRect(0,0,W,H);fundo(t);
  const k=eb((t-.1)/.9),y0=LERP(-9,0,clamp(k))+Math.sin(t*1.4)*.12;plataforma(y0,k);
  const entra=clamp((t-.7)/.7),px=LERP(-9,0,sm(entra)),hop=(t>.7&&t<1.4)?Math.abs(Math.sin((t-.7)/.7*2*Math.PI))*.6:0,walk=(t>.7&&t<1.4)?Math.sin(t*16)*.6:0;
  let r={armL:[0,0],armR:[0,0],shake:0,tilt:0,jump:0,dip:0};
  const B=DATA.beats;let cur=null;for(const b of B)if(t>=b.t0&&t<b.t1)cur=b;
  if(cur)r=reacao(cur,t);
  if(t>=DATA.cta.t0){const u=t-DATA.cta.t0,kk=Math.min(1,u*3);r.armL=[-3.1*kk,.95*kk];r.armR=[-3.1*kk,-.95*kk];r.jump=Math.abs(Math.sin(u*4.2))*.7}
  const mp=[px,y0+hop+r.jump,.9];sombra(mp[0],mp[2],1.3,.95,.32-(hop+r.jump)*.08,y0+.02);
  // cartões: no máximo 2 ao mesmo tempo, alternando esquerda e direita
  B.forEach((b,i)=>{if(t<b.t0)return;const saiT=Math.min(B[i+2]?B[i+2].t0:1e9,DATA.cta.t0),sai=sm((t-saiT)/.5);if(sai>=1)return;
    const kb=eb((t-b.t0)/.6),x=b.side*2.95;
    cartao([LERP(x,b.side*12,sai),LERP(14,4.9,clamp(kb))+Math.sin(t*2+i)*.15,-.6],-b.side*.5,-b.side*.08,.95,TW,TH,desenhaCartao(b,t-b.t0))});
  cubinho({pos:mp,yaw:.15,s:1.12,anim:{bobY:Math.sin(t*3.2)*.05+r.dip,armL:r.armL,armR:r.armR,legL:walk,legR:-walk,tilt:r.tilt,shake:r.shake}});
  desenha();
  const g=ctx.createRadialGradient(W/2,H*.5,H*.3,W/2,H*.5,H*.78);g.addColorStop(0,'rgba(0,0,0,0)');g.addColorStop(1,'rgba(2,6,20,.4)');ctx.fillStyle=g;ctx.fillRect(0,0,W,H);
  const kt=eo(t/.4);hl.style.opacity=kt;hl.style.transform=`translateY(${(1-kt)*30}px)`;bar.style.width=(300*eo((t-.3)/.5))+'px';
  CAPS.forEach(f=>{const vis=t>=f.ini&&t<f.fim;f.el.forEach((e,i)=>{const w=f.words[i],on=vis&&t>=w.t0,k3=eo((t-w.t0)/.18),falando=on&&t<w.t1;e.style.display=vis?'inline-block':'none';
    e.style.opacity=on?1:0;e.style.transform=`translateY(${on?(1-k3)*16:16}px) scale(${falando?1.08:1})`;e.style.color=(falando||e.dataset.hl)?'#E8A33D':'#F5F6FA'})});
}
</script></body></html>
'''


def render_reel_palco(roteiro, formato, workdir: Path, capa: Path = None, mostrar_link: bool = False):
    """Renderiza o Reel e devolve ([(quadro, segundos)], segundos totais, dados da cena)."""
    dados = montar_dados(roteiro, mostrar_link)
    seed = int(hashlib.sha1(clean(roteiro["gancho"]).encode()).hexdigest()[:6], 16) % 997 + 3
    pagina = (TEMPLATE.replace("__FONTDIR__", str(ASSETS)).replace("SEED", str(seed))
              .replace("__DATA__", json.dumps(dados, ensure_ascii=False)))
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    f = workdir / "palco.html"
    f.write_text(pagina, encoding="utf-8")
    n = int(round((dados["total"] + 0.4) * FPS))
    frames = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--allow-file-access-from-files"])
        pg = browser.new_page(viewport={"width": 1080, "height": 1920})
        erros = []
        pg.on("pageerror", lambda e: erros.append(str(e)[:200]))
        pg.goto(f"file://{f}")
        pg.wait_for_timeout(500)
        if erros:
            browser.close()
            raise RuntimeError("erro no cenário do Reel: " + erros[0])
        if capa:   # capa = título e mascote já no palco, antes dos cartões
            try:
                pg.evaluate(f"render({dados['hook']['dur'] * 0.95:.3f})")
                Path(capa).parent.mkdir(parents=True, exist_ok=True)
                pg.screenshot(path=str(capa))
            except Exception as e:
                print(f"[reel-palco] não consegui gerar a capa: {e}", flush=True)
        for i in range(n):
            pg.evaluate(f"render({i / FPS:.4f})")
            fp = workdir / f"q{i:04d}.jpg"
            pg.screenshot(path=str(fp), type="jpeg", quality=90)
            frames.append((fp, round(1 / FPS, 5)))
        if erros:
            browser.close()
            raise RuntimeError("erro no cenário do Reel: " + erros[0])
        browser.close()
    f.unlink(missing_ok=True)
    print(f"[reel-palco] {len(dados['beats'])} cartões, {dados['total']:.0f}s de vídeo ({n} quadros, formato {formato})", flush=True)
    return frames, dados["total"], dados
