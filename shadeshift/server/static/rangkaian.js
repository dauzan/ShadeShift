/* ShadeShift: Rekomendasi Rangkaian (docs/CONTRACT.md §29). The four panels and their wiring in 3D, with the current
 * flowing along the real path of each wiring, before and after a change a person approved; below it the AI's analysis,
 * the measured comparison of all wirings, and the buttons. Only the main parts: panels, terminals, wires, control box.
 * Plain JavaScript and SVG, nothing from the internet.
 *
 * The wiring comes from the relay matrix (rangkaian/daftar_kabel.md): A+ is fixed to P and D- to N (the control box's
 * positive and negative inputs); R1 A- to B+, R2 B- to N, R3 P to C+, R4 C- to D+, R5 B- to C+, R6 B+ to D+, R7 A- to N,
 * R8 P to B+, R9 C- to N, R10 P to D+.  4S: R1 R4 R5.  2S2P: R1 to R4.  TCT: R1 to R4 and R6.  4P: R2 R3 R7 to R10.
 * Every wire of a rangkaian is drawn in that rangkaian's own colour (WARNA), so one view shows one rangkaian only.
 * Each wire is listed in the direction the current flows (out of a positive terminal, into a negative one; P is where
 * the current enters the control box, N where it returns). The TCT cross-link only balances the two strings: no arrow.
 */
"use strict";

const WIRING = {
  "4S": [["A+", "P"], ["B+", "A-"], ["C+", "B-"], ["D+", "C-"], ["N", "D-"]],
  "2S2P": [["A+", "P"], ["B+", "A-"], ["N", "B-"], ["C+", "P"], ["D+", "C-"], ["N", "D-"]],
  "TCT": [["A+", "P"], ["B+", "A-"], ["N", "B-"], ["C+", "P"], ["D+", "C-"], ["N", "D-"], ["B+", "D+", "tie"]],
  "4P": [["A+", "P"], ["N", "A-"], ["B+", "P"], ["N", "B-"], ["C+", "P"], ["N", "C-"], ["D+", "P"], ["N", "D-"]],
};
const NAMA = {"4S": "Seri (4S)", "2S2P": "Seri-paralel (2S2P)", "TCT": "Silang (TCT)", "4P": "Paralel (4P)"};
const WARNA = {"4S": "#2563eb", "2S2P": "#0d9488", "TCT": "#7c3aed", "4P": "#ea580c"};
const kecil = (s) => s.charAt(0).toLowerCase() + s.slice(1);            // 'seri (4S)': the code keeps its capitals

// ---------------- geometry (units; x right, y towards the front, z up) ----------------
const PW = 44, PH = 26, CG = 22, RG = 24, COLS = 9, ROWS = 4, TH = 2.2;
const ORIGIN = {A: [0, 0], C: [PW + CG, 0], B: [0, PH + RG], D: [PW + CG, PH + RG]};
const BOX = {x: 2 * PW + CG + 30, y: PH + RG / 2 - 11, w: 20, h: 22};
const CH = {0: PH + RG / 2, 1: 2 * PH + RG + 10};                 // wire channels below each row of panels
const GUTTER = [-12, PW + CG / 2, 2 * PW + CG + 14];               // vertical lanes: left, between the columns, right

function node(id) {
  if (id === "P") return {x: BOX.x + BOX.w * 0.3, y: BOX.y + BOX.h + 0.5, ch: BOX.y + BOX.h + 5, box: true};
  if (id === "N") return {x: BOX.x + BOX.w * 0.75, y: BOX.y + BOX.h + 0.5, ch: BOX.y + BOX.h + 5, box: true};
  const m = id[0], [ox, oy] = ORIGIN[m], row = m === "A" || m === "C" ? 0 : 1;
  return {x: ox + PW * (id[1] === "+" ? 0.74 : 0.26), y: oy + PH + 1.2, ch: CH[row]};
}

/** An orthogonal route from terminal a to terminal b on the base plane: down to a's channel, along it (through a
 * vertical lane when the channels differ), then to b. k spreads parallel wires apart. */
function route(a, b, k = 0) {
  const A = node(a), B = node(b), o = (k % 4) * 2.4;
  const ca = A.ch + o, cb = B.ch + o;
  let pts;
  if (Math.abs(ca - cb) < 0.1) {
    pts = [[A.x, A.y], [A.x, ca], [B.x, cb], [B.x, B.y]];
  } else {
    const g = (A.box || B.box ? GUTTER[2] : GUTTER.reduce((best, x) => (Math.abs(A.x - x) + Math.abs(B.x - x) <
                                                                         Math.abs(A.x - best) + Math.abs(B.x - best) ? x : best)))
              + (A.box || B.box ? o : -o);
    pts = [[A.x, A.y], [A.x, ca], [g, ca], [g, cb], [B.x, cb], [B.x, B.y]];
  }
  return pts.map(([x, y], i) => [x, y, i === 0 || i === pts.length - 1 ? 1.2 : 0.35]);
}

function wires(topology) {
  return (WIRING[topology] || []).map(([a, b, kind], k) => (
    {from: a, to: b, tie: kind === "tie", pts: route(a, b, k), color: WARNA[topology]}));
}

function project(p, cam) {
  const yaw = cam.yaw * Math.PI / 180, pitch = cam.pitch * Math.PI / 180;
  const x = p[0] - 70, y = p[1] - 40, z = p[2];
  const x1 = x * Math.cos(yaw) - y * Math.sin(yaw), y1 = x * Math.sin(yaw) + y * Math.cos(yaw);
  return [x1, y1 * Math.sin(pitch) - z * Math.cos(pitch), y1 * Math.cos(pitch) + z * Math.sin(pitch)];
}
function mix(hex, k) {
  const c = parseInt(hex.slice(1), 16), f = (v) => Math.max(0, Math.min(255, Math.round(v * k)));
  return `rgb(${f(c >> 16)},${f((c >> 8) & 255)},${f(c & 255)})`;
}

if (typeof module !== "undefined") module.exports = {WIRING, NAMA, WARNA, ORIGIN, BOX, node, route, wires, project};

// ======================= page (browser only) =======================
if (typeof document !== "undefined") {
  const NS = "http://www.w3.org/2000/svg", API = "/api/v1";
  const params = new URLSearchParams(location.search), DEVICE = params.get("device_id");
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const w2 = (x) => (x == null ? "-" : Number(x).toFixed(2).replace(".", ","));
  const jam = (iso) => (iso ? new Date(iso).toLocaleTimeString("id-ID", {hour: "2-digit", minute: "2-digit"}) : "-");
  const CAM = {yaw: -22, pitch: 52};
  let state = null, pratinjau = false, satu = false, pending = null, viewKey = "", flows = [];

  async function api(path, opts) {
    const r = await fetch(API + path, {headers: {"Content-Type": "application/json"}, ...opts});
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  const P2 = (p) => project(p, CAM);
  const pts = (list) => list.map((p) => { const q = P2(p); return `${q[0].toFixed(2)},${q[1].toFixed(2)}`; }).join(" ");

  /** One 3D view of a wiring: the panels (raised boxes with cells), their terminals, the wires, the control box. */
  function viewSvg(topology, aktif) {
    const svg = el("svg", {role: "img", "aria-label": `Rangkaian ${NAMA[topology] || "tidak diketahui"}`});
    const defs = el("defs", {}, svg);
    const fg = el("radialGradient", {id: `fl${topology}`, cx: "50%", cy: "50%", r: "50%"}, defs);
    el("stop", {offset: "0%", "stop-color": "#fffbea"}, fg);
    el("stop", {offset: "40%", "stop-color": "#fde047", "stop-opacity": 0.9}, fg);
    el("stop", {offset: "100%", "stop-color": "#facc15", "stop-opacity": 0}, fg);
    const all = [];
    for (const m of "ABCD") { const [ox, oy] = ORIGIN[m]; all.push([ox, oy, TH], [ox + PW, oy + PH, 0]); }
    for (const x of [BOX.x, BOX.x + BOX.w]) for (const y of [BOX.y, BOX.y + BOX.h]) for (const z of [0, 22]) all.push([x, y, z]);
    all.push([GUTTER[0] - 4, CH[1] + 12, 0], [GUTTER[2] + 12, CH[1] + 12, 0]);
    const q = all.map(P2), xs = q.map((p) => p[0]), ys = q.map((p) => p[1]);
    const x0 = Math.min(...xs) - 8, x1 = Math.max(...xs) + 8, y0 = Math.min(...ys) - 18, y1 = Math.max(...ys) + 8;
    svg.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    // soft shadows of the panels and the box
    for (const m of "ABCD") {
      const [ox, oy] = ORIGIN[m];
      el("polygon", {points: pts([[ox + 1.5, oy + 2, 0], [ox + PW + 2.5, oy + 2, 0], [ox + PW + 2.5, oy + PH + 3, 0], [ox + 1.5, oy + PH + 3, 0]]),
                     fill: "#0f172a", opacity: 0.08}, svg);
    }
    // wires on the base plane
    const ws = topology ? wires(topology) : [];
    for (const w of ws) {
      el("polyline", {points: pts(w.pts), fill: "none", stroke: w.color, "stroke-width": 1.5, "stroke-linejoin": "round",
                      "stroke-linecap": "round", "stroke-dasharray": w.tie ? "3 2" : "none", opacity: aktif ? 1 : 0.85}, svg);
    }
    // panels
    for (const m of "ABCD") {
      const [ox, oy] = ORIGIN[m];
      const top = [[ox, oy, TH], [ox + PW, oy, TH], [ox + PW, oy + PH, TH], [ox, oy + PH, TH]];
      el("polygon", {points: pts([[ox, oy + PH, 0], [ox + PW, oy + PH, 0], [ox + PW, oy + PH, TH], [ox, oy + PH, TH]]), fill: "#9aa6b4"}, svg);
      el("polygon", {points: pts([[ox + PW, oy, 0], [ox + PW, oy + PH, 0], [ox + PW, oy + PH, TH], [ox + PW, oy, TH]]), fill: "#b4bec9"}, svg);
      el("polygon", {points: pts(top), fill: "#c9d1db", stroke: "#94a3b8", "stroke-width": 0.2}, svg);
      const f = 1.3, cw = (PW - 2 * f) / COLS, chh = (PH - 2 * f) / ROWS;
      for (let c = 0; c < COLS; c++) for (let r = 0; r < ROWS; r++) {
        const x = ox + f + c * cw, y = oy + f + r * chh;
        el("polygon", {points: pts([[x + 0.15, y + 0.15, TH + 0.01], [x + cw - 0.15, y + 0.15, TH + 0.01], [x + cw - 0.15, y + chh - 0.15, TH + 0.01],
                                    [x + 0.15, y + chh - 0.15, TH + 0.01]]), fill: (c + r) % 2 ? "#1c3253" : "#1f3759"}, svg);
      }
      const c = P2([ox + PW / 2, oy + PH / 2, TH + 0.1]);
      const t = el("text", {x: c[0], y: c[1] + 3, "text-anchor": "middle", "font-size": 9, "font-weight": 700, fill: "#ffffff", opacity: 0.9}, svg);
      t.textContent = m;
      for (const s of ["-", "+"]) {                                     // terminals on the front edge: black and red
        const n = node(m + s);
        el("polygon", {points: pts([[n.x - 1.6, n.y - 1.2, 0], [n.x + 1.6, n.y - 1.2, 0], [n.x + 1.6, n.y - 1.2, 1.8], [n.x - 1.6, n.y - 1.2, 1.8]]),
                       fill: "#4b5563"}, svg);
      }
    }
    // control box with its two inputs
    const b = BOX, H = 12;
    el("polygon", {points: pts([[b.x, b.y + b.h, 0], [b.x + b.w, b.y + b.h, 0], [b.x + b.w, b.y + b.h, H], [b.x, b.y + b.h, H]]), fill: "#6b7280"}, svg);
    el("polygon", {points: pts([[b.x + b.w, b.y, 0], [b.x + b.w, b.y + b.h, 0], [b.x + b.w, b.y + b.h, H], [b.x + b.w, b.y, H]]), fill: "#575d66"}, svg);
    el("polygon", {points: pts([[b.x, b.y, H], [b.x + b.w, b.y, H], [b.x + b.w, b.y + b.h, H], [b.x, b.y + b.h, H]]), fill: "#8a919c"}, svg);
    for (const [id, col] of [["P", "#4b5563"], ["N", "#4b5563"]]) {
      const n = node(id);
      el("polygon", {points: pts([[n.x - 1.6, n.y, 2], [n.x + 1.6, n.y, 2], [n.x + 1.6, n.y, 5], [n.x - 1.6, n.y, 5]]), fill: col}, svg);
    }
    const lb = P2([b.x + b.w / 2, b.y + b.h / 2, H + 7]);                  // above the box, clear of the wires
    const tl = el("text", {x: lb[0], y: lb[1], "text-anchor": "middle", "font-size": 4.6, "font-weight": 600, fill: "#334155"}, svg);
    tl.textContent = "Kotak kendali";
    // flashes along each wire, in the direction of the current (not on the balancing cross-link)
    const g = el("g", {}, svg);
    if (aktif) {
      for (const w of ws.filter((x) => !x.tie)) {
        const p2 = w.pts.map(P2), seg = [];
        let len = 0;
        for (let i = 0; i < p2.length - 1; i++) { const d = Math.hypot(p2[i + 1][0] - p2[i][0], p2[i + 1][1] - p2[i][1]); seg.push(d); len += d; }
        const dots = Array.from({length: Math.max(2, Math.round(len / 28))}, () => el("circle", {r: 1.9, fill: `url(#fl${topology})`}, g));
        flows.push({p2, seg, len, dots});
      }
    }
    return svg;
  }

  function flowFrame(now) {
    for (const f of flows) {
      f.dots.forEach((dot, k) => {
        let s = ((now / 1000) * 22 + k * f.len / f.dots.length) % f.len, i = 0;
        while (i < f.seg.length - 1 && s > f.seg[i]) { s -= f.seg[i]; i++; }
        const a = f.p2[i], b = f.p2[i + 1], t = f.seg[i] ? s / f.seg[i] : 0;
        dot.setAttribute("cx", a[0] + (b[0] - a[0]) * t);
        dot.setAttribute("cy", a[1] + (b[1] - a[1]) * t);
      });
    }
    requestAnimationFrame(flowFrame);
  }

  function header(text, sub) { return `<h3>${esc(text)}${sub ? `<span>${esc(sub)}</span>` : ""}</h3>`; }

  function renderViews() {
    const s = state, box = $("views");
    const t = s.terakhir, menit = t ? (Date.now() - Date.parse(t.at)) / 60000 : 1e9;
    const split = pending || (t && menit <= 60 && !satu);
    let views;
    if (split) {
      const dari = pending ? pending.dari : t.dari, ke = pending ? pending.ke : t.ke;
      const sb = pending ? null : t.sebelum, ss = pending ? null : t.sesudah;
      const naik = !pending && t.naik_persen != null ? `, ${t.naik_persen >= 0 ? "naik" : "turun"} ${Math.abs(t.naik_persen)} persen` : "";
      views = [{topology: dari, title: `Sebelum: ${NAMA[dari] || "Semua relai terbuka"}`, sub: sb ? `${w2(sb.pmax)} watt, pukul ${jam(sb.at)}` : "", aktif: false},
               {topology: ke, title: `Sesudah: ${NAMA[ke]}`, aktif: true,
                sub: pending ? "Sedang dipindah dengan urutan aman" : ss ? `${w2(ss.pmax)} watt, pukul ${jam(ss.at)}${naik}` : "Menunggu pengukuran pertama"}];
    } else if (pratinjau && s.rekomendasi) {
      views = [{topology: s.rekomendasi, title: `Pratinjau: ${s.nama_rekomendasi}`, sub: "Belum diterapkan", aktif: true}];
    } else {
      const ukur = (s.perbandingan.find((r) => r.rangkaian === s.sekarang) || {}).pmax;
      views = [{topology: s.sekarang, title: `Sekarang: ${s.nama_sekarang}`, sub: ukur ? `${w2(ukur)} watt saat dibandingkan` : "", aktif: !!s.sekarang}];
    }
    const key = JSON.stringify(views);
    $("pratinjau").hidden = split || !s.rekomendasi;
    $("pratinjau").textContent = pratinjau ? "Lihat rangkaian sekarang" : "Lihat rangkaian saran";
    $("satu").hidden = !split || !!pending;
    if (key === viewKey) return;
    viewKey = key;
    const shown = [...new Set(views.map((v) => v.topology).filter((t) => t))];   // the legend: only the rangkaian on screen
    $("legend").innerHTML = shown.map((t) => `<span><i style="background:${WARNA[t]}"></i>${esc(NAMA[t])}</span>`).join("") +
      (shown.includes("TCT") ? `<span>Garis putus-putus: sambungan silang di tengah</span>` : "") +
      `<span><i style="background:#facc15"></i>Kilatan: arah aliran listrik</span>`;
    flows = [];
    box.innerHTML = "";
    for (const v of views) {
      const d = document.createElement("div");
      d.className = "view";
      d.innerHTML = header(v.title, v.sub);
      d.appendChild(viewSvg(v.topology, v.aktif));
      box.appendChild(d);
    }
  }

  function renderAnalysis() {
    const s = state;
    const max = Math.max(...s.perbandingan.map((r) => r.pmax || 0), 0.001);
    const terbaik = s.perbandingan.filter((r) => r.bisa && r.pmax).sort((a, b) => b.pmax - a.pmax)[0];
    let rows = "";
    for (const r of s.perbandingan) {
      const cls = ["row", r.rangkaian === s.sekarang ? "now" : "", terbaik && r.rangkaian === terbaik.rangkaian ? "best" : "", r.bisa ? "" : "off"].join(" ");
      rows += `<div class="${cls}"><span class="name">${esc(r.nama)}${r.rangkaian === s.sekarang ? ", sekarang" : ""}</span>` +
        `<span class="track"><span class="fill" style="display:block;width:${r.pmax ? Math.round(r.pmax / max * 100) : 0}%"></span></span>` +
        `<span class="w">${r.pmax ? w2(r.pmax) + " W" : "-"}</span></div>` + (r.catatan ? `<p class="off-note">${esc(r.catatan)}</p>` : "");
    }
    const cmpNote = s.waktu_banding ? `Diukur pukul ${jam(s.waktu_banding)}${s.segar ? "" : "; sudah lama, bandingkan lagi"}.` :
      "Belum ada perbandingan.";
    let html = `<div class="ai"><div class="badge2">AI</div><div class="grid">` +
      `<div class="box main"><h4>Analisis AI</h4><p class="judul">${esc(s.judul)}</p>` +
      s.alasan.map((x) => `<p>${esc(x)}</p>`).join("") + (s.keuntungan ? `<p class="untung">${esc(s.keuntungan)}</p>` : "") +
      `</div><div class="box cmp"><h4>Daya tiap rangkaian</h4>${rows}<p class="note">${esc(cmpNote)} Relai hanya berpindah untuk ` +
      `mengukur, lalu kembali ke rangkaian semula.</p></div></div>` +
      (s.demo ? `<p class="note" style="color:#92400e">Data demo: kurva lab yang direkam, bukan pengukuran saat ini.</p>` : "") + `</div>`;
    const t = s.terakhir;
    if (t && t.sesudah && t.naik_persen != null) {
      html += `<p class="done">Rangkaian diubah pukul ${jam(t.at)} dari ${esc(kecil(NAMA[t.dari] || "semua relai terbuka"))} ke ` +
        `${esc(kecil(NAMA[t.ke]))} atas persetujuan pengguna. Terukur sesudahnya: daya ${t.naik_persen >= 0 ? "naik" : "turun"} ` +
        `${Math.abs(t.naik_persen)} persen.</p>`;
    }
    html += `<div class="acts"><button id="banding" class="btn">Bandingkan semua rangkaian</button>`;
    if (s.rekomendasi) {
      html += `<button id="terapkan" class="btn primary"${s.boleh && s.online ? "" : " disabled"}>Terapkan saran: ubah ke ${esc(s.nama_rekomendasi)}</button>`;
    }
    if (s.kembali) html += `<button id="kembali" class="btn">Kembalikan ke ${esc(NAMA[s.kembali])}</button>`;
    html += `</div><p class="hint">` + (s.jeda_menit ? `Rangkaian baru saja diubah: saran berikutnya bisa diterapkan dalam sekitar ` +
      `${s.jeda_menit} menit. ` : "") + (s.online ? "" : "Alat tidak terhubung. ") +
      `Bandingkan semua rangkaian butuh sekitar 20 detik. Rangkaian hanya diubah setelah Anda menyetujuinya.</p>`;
    $("analisis").innerHTML = html;
    $("banding").onclick = () => api(`/devices/${encodeURIComponent(DEVICE)}/commands`,
      {method: "POST", body: JSON.stringify({kind: "action", command: "compare_wirings", params: {}})})
      .then(() => { $("err").textContent = ""; setTimeout(load, 1500); }).catch((e) => { $("err").textContent = "Perbandingan gagal dimulai: " + e.message; });
    if ($("terapkan")) $("terapkan").onclick = () => tanya(s.rekomendasi, s.kerugian);
    if ($("kembali")) $("kembali").onclick = () => tanya(s.kembali, []);
  }

  /** The approval dialog: what changes and what can go wrong, then the person's decision. */
  function tanya(ke, risiko) {
    $("dlgjudul").textContent = `Ubah rangkaian ke ${kecil(NAMA[ke])}?`;
    $("dlgisi").textContent = `Relai akan memindah keempat panel dari ${kecil(state.nama_sekarang)} ke ${kecil(NAMA[ke])} ` +
      "dengan urutan aman: aliran listrik dihentikan dulu, relai dibuka, rangkaian baru disambung, lalu tegangannya diperiksa.";
    const list = risiko.length ? risiko : ["Listrik terputus beberapa detik saat relai berpindah.",
                                           "Jangan menyentuh kabel selama perpindahan: tegangan bisa mencapai sekitar 88 volt."];
    $("dlgrisiko").innerHTML = list.map((x) => `<li>${esc(x)}</li>`).join("");
    $("dlg").classList.add("open");
    $("dlgbatal").onclick = () => $("dlg").classList.remove("open");
    $("dlgya").onclick = async () => {
      $("dlg").classList.remove("open");
      try {
        await api(`/devices/${encodeURIComponent(DEVICE)}/rangkaian/terapkan`, {method: "POST", body: JSON.stringify({target: ke})});
        pending = {dari: state.sekarang, ke, at: Date.now()};
        satu = false;
        $("err").textContent = "";
        render();
        setTimeout(load, 1500);
      } catch (e) { $("err").textContent = "Perubahan ditolak: " + e.message; }
    };
  }

  function render() {
    if (!state) return;
    $("demo").hidden = !state.demo;
    $("now").textContent = `Sekarang: ${state.nama_sekarang}`;
    $("meta").textContent = state.online ? "" : "Alat tidak terhubung";
    renderViews();
    renderAnalysis();
    postHeight();
  }

  const EMBEDDED = window.parent !== window;
  if (EMBEDDED) document.documentElement.style.overflow = "hidden";
  function postHeight() {
    if (!EMBEDDED) return;
    const w = document.querySelector(".wrap");
    window.parent.postMessage({type: "shadeshift-tinggi", h: Math.ceil(w.getBoundingClientRect().bottom + window.scrollY + 24)}, "*");
  }
  if (EMBEDDED && window.ResizeObserver) new ResizeObserver(() => postHeight()).observe(document.querySelector(".wrap"));

  async function load() {
    if (!DEVICE) { $("now").textContent = "Pilih perangkat di dasbor."; return; }
    try {
      state = await api(`/devices/${encodeURIComponent(DEVICE)}/rangkaian`);
      if (pending && state.terakhir && state.terakhir.ke === pending.ke && Date.parse(state.terakhir.at) >= pending.at - 60000 &&
          (state.sekarang === pending.ke || Date.now() - pending.at > 60000)) pending = null;   // the switch is done
      $("err").textContent = "";
    } catch (e) { $("err").textContent = "Tidak dapat membaca data: " + e.message; }
    render();
  }
  $("pratinjau").onclick = () => { pratinjau = !pratinjau; render(); };
  $("satu").onclick = () => { satu = true; render(); };
  window.addEventListener("resize", postHeight);
  load();
  setInterval(load, 3000);
  requestAnimationFrame(flowFrame);
}
