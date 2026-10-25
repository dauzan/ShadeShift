// SHADESHIFT: halaman web ESP32 (hanya baca + tombol STOP). Tanpa internet: semua CSS/JS di sini, kurva digambar dengan SVG.
// Data dari GET /data (JSON) tiap 2 detik; STOP = POST /off (membuka semua relai, juga menghentikan PILIH/DIAG/SIKLUS).
#pragma once
static const char HALAMAN_WEB[] = R"HTML(<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SHADESHIFT</title>
<style>
:root{--bg:#fff;--fg:#1d2433;--mut:#5b6472;--line:#d6dae0;--acc:#2a6fdb;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#14181f;--fg:#e6e9ee;--mut:#9aa3ad;--line:#2c333d;--acc:#7aa7ff;--bad:#ff7a6b}}
body{font-family:system-ui,sans-serif;margin:0 auto;padding:16px;background:var(--bg);color:var(--fg);max-width:640px}
h1{font-size:1.25rem;margin:0 0 4px}.mut{color:var(--mut);font-size:.85rem}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
.k{border:1px solid var(--line);border-radius:8px;padding:8px;font-size:.85rem;color:var(--mut)}
.k b{display:block;font-size:1.1rem;color:var(--fg);overflow-wrap:anywhere}
svg{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:8px}
button{width:100%;padding:14px;font-size:1rem;font-weight:600;border:0;border-radius:8px;background:var(--bad);color:#fff;margin:12px 0 8px}
#warn{color:var(--bad);font-weight:600;min-height:1.2em}
</style></head><body>
<h1>&#9728; SHADESHIFT</h1>
<div class="mut">Halaman dari ESP32 (hanya baca). Pindah susunan lewat laptop atau Serial Monitor.</div>
<div class="grid">
<div class="k">Susunan aktif<b id="topo">-</b></div>
<div class="k">Pmax sapuan terakhir<b id="pmax">-</b></div>
<div class="k">Pemilih AI (di ESP32)<b id="pil">-</b></div>
<div class="k">Diagnosis AI (di ESP32)<b id="diag">-</b></div>
</div>
<svg id="kurva" viewBox="0 0 320 180" role="img" aria-label="Kurva I-V sapuan terakhir"></svg>
<div class="mut" id="ket">Belum ada sapuan.</div>
<div id="warn"></div>
<button onclick="off()">&#9209; STOP: buka semua relai</button>
<div class="mut">Firmware <span id="fw">-</span> &middot; diperbarui tiap 2 detik &middot; 4S bisa sekitar 88 V DC: STOP sebelum menyentuh kabel</div>
<script>
function g(i){return document.getElementById(i)}
async function muat(){try{const d=await(await fetch('/data')).json();
g('topo').textContent=d.topologi||'terbuka';g('fw').textContent=d.fw;
g('pmax').textContent=d.pmax>0?d.pmax.toFixed(3)+' W':'-';
g('pil').textContent=d.pemilih||'-';
g('diag').textContent=d.diagnosis?d.diagnosis+' ('+Math.round(d.yakin*100)+' %)':'-';
g('warn').textContent=d.peringatan||'';
const p=d.titik||[];if(p.length>1){let vm=0,im=0;for(const t of p){vm=Math.max(vm,t[0]);im=Math.max(im,t[1])}
const s=p.map(t=>(24+t[0]/(vm||1)*288).toFixed(1)+','+(160-t[1]/(im||1)*145).toFixed(1)).join(' ');
g('kurva').innerHTML='<line x1="24" y1="160" x2="316" y2="160" stroke="currentColor" opacity=".35"/>'+
'<line x1="24" y1="10" x2="24" y2="160" stroke="currentColor" opacity=".35"/>'+
'<polyline fill="none" stroke="var(--acc)" stroke-width="2" points="'+s+'"/>'+
'<text x="300" y="175" font-size="11" fill="currentColor">V</text><text x="6" y="16" font-size="11" fill="currentColor">I</text>';
g('ket').textContent=d.label+': Voc '+d.voc.toFixed(2)+' V, Isc '+(d.isc*1000).toFixed(1)+' mA';}
}catch(e){g('warn').textContent='ESP32 tidak menjawab (sedang menyapu, atau WiFi terputus)'}}
async function off(){try{await fetch('/off',{method:'POST'})}catch(e){}muat()}
muat();setInterval(muat,2000);
</script></body></html>)HTML";
