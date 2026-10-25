/* ShadeShift consumer view (docs/CONTRACT.md §19): a solid 3D model of the real array, seen at a raised three-quarter
 * angle, with the condition of each panel from the server (/api/v1/twin/state -> kondisi). Plain JavaScript and SVG,
 * nothing from the internet.
 *
 * The model: four landscape panels of 9 x 4 cells (A top-left, B bottom-left, C top-right, D bottom-right, as built),
 * each with its terminal box and 1N5822 bypass diode on the back at the bottom edge, cables under the array to the Wago
 * connectors beside it, on the sun-facing slope of a house roof (eight roof types to choose from: gable, hip, Dutch gable,
 * gambrel, kampung with a porch, saltbox, shed, flat with a tilted rack); light grey walls with framed windows and a
 * wooden door, a gutter and downpipe, the control box (the "power") on the front wall. The array, its parts and
 * the Wago strip are drawn in ROOF coordinates (the plane of the panels) and tilted by W(); the house in world
 * coordinates. Flashes of light run a loop from the control box up to the panels, through D, C, A, B and back, while
 * monitoring is on and the newest measurement is recent (the rig carries current during a sweep).
 * Orthographic camera (yaw, pitch), framed close: the roof with the panels fills the upper left, the front wall with the
 * control box the lower right, and the house's right corner shows against the background. The user drags to rotate
 * (pitch stays above), "Atur ulang tampilan" returns, a click on a panel zooms in. What the model shows comes only from the measured condition:
 *   object on a panel  -> the panel darkens (darker the more light it lost) with a red radial glow; the whole panel,
 *                         because the position on its surface is not measurable (36 cells in series, one bypass diode);
 *   bypass diode       -> panels turn see-through, blue glow at that panel's terminal box and diode;
 *   cable / connector  -> panels turn see-through, blue glow along that panel's cable to the Wago connector;
 *   less light overall -> all four panels darken evenly by the array's loss (a cloud, or dust everywhere).
 */
"use strict";

// ---------------- geometry (cm; x right, y towards the front row B/D, z up) ----------------
const CELL_W = 3.6, CELL_H = 5.0, FRAME = 1.4, GAP = 1.2, DEPTH = 3.0, COLS = 9, ROWS = 4;
const PANEL_W = COLS * CELL_W + 2 * FRAME, PANEL_H = ROWS * CELL_H + 2 * FRAME;
const ORIGIN = {A: [0, 0], C: [PANEL_W + GAP, 0], B: [0, PANEL_H + GAP], D: [PANEL_W + GAP, PANEL_H + GAP]};
const ARRAY_W = 2 * PANEL_W + GAP, ARRAY_H = 2 * PANEL_H + GAP;
const RAIL = 4, TOP = RAIL + DEPTH;                 // panels sit on rails 4 cm above the roof surface
const WAGO = {x: ARRAY_W + 6, y: 10, w: 5, h: ARRAY_H - 20, z0: 0, z1: 2.5};      // roof coordinates
const ROOF = {x0: -28, x1: ARRAY_W + 30, y0: -34, y1: ARRAY_H + 12, t: 2.5};     // the panel slope, roof coordinates
const TILT = 24 * Math.PI / 180;                    // the panel slope faces the sun, towards the front
const EAVE = 44;                                    // height of the front eave above the ground (cm)
const ROOF_COLOR = "#f4a364";                       // rgb(244 163 100)
const WALL_COLOR = "#c9d0d8";                       // young grey
/** Roof types (as in the usual roof-type charts) that carry the array on their front slope. back: run of the back slope
 * as a share of the front one (0 = a single slope); hip: horizontal depth of the side hips; gablet: the hips stop at this
 * share of the height and a small upright gable closes the end (Dutch gable); skirt: a steep band of depth d and height
 * h below the panel slope, front and back (gambrel); porch: a lean-to porch roof on posts over the door; flat: panels on
 * a rack. */
const ROOF_TYPES = {
  pelana: {name: "Pelana", back: 1},
  perisai: {name: "Perisai (limasan)", back: 1, hip: 24},
  gablet: {name: "Perisai berpelana", back: 1, hip: 24, gablet: 0.55},
  gambrel: {name: "Gambrel", back: 1, skirt: {d: 7, h: 15}},
  kampung: {name: "Kampung dengan emper", back: 1, porch: true},
  saltbox: {name: "Saltbox", back: 0.45},
  sandar: {name: "Sandar", back: 0},
  datar: {name: "Datar", flat: true},
};
let ROOF_TYPE = "pelana";
let PANEL_EAVE = EAVE;                              // world height of the panel plane's lower edge
let HOUSE, BOX, CENTER, ROOFGEO;
const PANELS = ["A", "B", "C", "D"];
const HOME = {yaw: -48, pitch: 33};                 // from the front left: the eave rises to the right at about 30 degrees
const LIGHT = norm([-0.35, 0.55, 0.76]);           // light from the front left, above

function norm(v) { const l = Math.hypot(...v); return v.map((x) => x / l); }
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

/** Roof coordinates (x along the ridge, y down the slope towards the front, z out of the roof) -> world (z up). */
function W(p) {
  return [p[0], ROOF.y0 + (p[1] - ROOF.y0) * Math.cos(TILT) + p[2] * Math.sin(TILT),
          PANEL_EAVE + (ROOF.y1 - p[1]) * Math.sin(TILT) + p[2] * Math.cos(TILT)];
}
/** A direction (face normal) from roof to world coordinates. */
function R(n) { return [n[0], n[1] * Math.cos(TILT) + n[2] * Math.sin(TILT), -n[1] * Math.sin(TILT) + n[2] * Math.cos(TILT)]; }

function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }

/** Set the roof type: the house (world), the roof faces with outward normals, the rack legs of a flat roof, the control
 * box on the front wall, and the camera centre. The panel slope (roof coordinates) is the same for every type. */
function setRoof(type) {
  ROOF_TYPE = ROOF_TYPES[type] ? type : "pelana";
  const rt = ROOF_TYPES[ROOF_TYPE], L = ROOF.y1 - ROOF.y0, run = L * Math.cos(TILT), rise = L * Math.sin(TILT);
  const x0 = ROOF.x0, x1 = ROOF.x1, th = ROOF.t, Yr = ROOF.y0, Yf = Yr + run, E = EAVE;
  const sk = rt.skirt || null, sd = sk ? sk.d : 0, sh = sk ? sk.h : 0;
  let faces = [], legs = [], zRoof, Yb, Zr, top, ridge = null, hipY = Yr, knees = [], Yo = Yf, Ybo;
  if (rt.flat) {
    Zr = E + 4;
    PANEL_EAVE = Zr + 7;                              // the panels on a rack above the flat roof
    Yb = Yr;
    Ybo = Yb;
    zRoof = () => Zr;
    faces = [{p: [[x0, Yb, Zr], [x1, Yb, Zr], [x1, Yf, Zr], [x0, Yf, Zr]], main: true},
             [[x0, Yf, Zr], [x1, Yf, Zr], [x1, Yf, Zr - th], [x0, Yf, Zr - th]],
             [[x0, Yb, Zr], [x1, Yb, Zr], [x1, Yb, Zr - th], [x0, Yb, Zr - th]],
             [[x0, Yb, Zr], [x0, Yf, Zr], [x0, Yf, Zr - th], [x0, Yb, Zr - th]],
             [[x1, Yb, Zr], [x1, Yf, Zr], [x1, Yf, Zr - th], [x1, Yb, Zr - th]]];
    for (const x of [3, ARRAY_W / 2, ARRAY_W - 3]) for (const y of [2, ARRAY_H - 2]) {
      const a = W([x, y, RAIL]);
      legs.push([a, [a[0], a[1], Zr]]);
    }
    top = Zr;
  } else {
    const E2 = E + sh;                                // lower edge of the panel slope (above a gambrel's steep band)
    PANEL_EAVE = E2;
    Zr = E2 + rise;
    const runB = rt.back * run;
    Yb = Yr - runB;
    Yo = Yf + sd;                                     // the outer front eave
    Ybo = runB > 0 ? Yb - sd : Yb;
    const main = (Y) => (Y >= Yr ? E2 + (Yf - Y) / run * rise : runB > 0 ? E2 + (Y - Yb) / runB * rise : Zr);
    zRoof = (Y) => (sk && Y > Yf ? E2 - (Y - Yf) / sd * sh : sk && runB > 0 && Y < Yb ? E2 - (Yb - Y) / sd * sh : main(Y));
    if (rt.hip) {
      const h = rt.hip, g = rt.gablet || 0, zg = E + g * rise, Ygf = Yf - g * run, Ygb = Yb + g * runB;
      const edges = [[[x0, Yf, E], [x1, Yf, E], [x1, Yf, E - th], [x0, Yf, E - th]],
                     [[x0, Yb, E], [x1, Yb, E], [x1, Yb, E - th], [x0, Yb, E - th]],
                     [[x0, Yb, E], [x0, Yf, E], [x0, Yf, E - th], [x0, Yb, E - th]],
                     [[x1, Yb, E], [x1, Yf, E], [x1, Yf, E - th], [x1, Yb, E - th]]];
      if (g) {
        hipY = Ygf;
        faces = [{p: [[x0 + h, Yr, Zr], [x1 - h, Yr, Zr], [x1 - h, Ygf, zg], [x1, Yf, E], [x0, Yf, E], [x0 + h, Ygf, zg]], main: true},
                 [[x0 + h, Yr, Zr], [x1 - h, Yr, Zr], [x1 - h, Ygb, zg], [x1, Yb, E], [x0, Yb, E], [x0 + h, Ygb, zg]],
                 [[x0, Yb, E], [x0 + h, Ygb, zg], [x0 + h, Ygf, zg], [x0, Yf, E]],
                 [[x1, Yf, E], [x1 - h, Ygf, zg], [x1 - h, Ygb, zg], [x1, Yb, E]],
                 {p: [[x0 + h, Ygb, zg], [x0 + h, Yr, Zr], [x0 + h, Ygf, zg]], wall: true},
                 {p: [[x1 - h, Ygf, zg], [x1 - h, Yr, Zr], [x1 - h, Ygb, zg]], wall: true}, ...edges];
      } else {
        faces = [{p: [[x0 + h, Yr, Zr], [x1 - h, Yr, Zr], [x1, Yf, E], [x0, Yf, E]], main: true},
                 [[x0 + h, Yr, Zr], [x1 - h, Yr, Zr], [x1, Yb, E], [x0, Yb, E]],
                 [[x0, Yb, E], [x0 + h, Yr, Zr], [x0, Yf, E]],
                 [[x1, Yf, E], [x1 - h, Yr, Zr], [x1, Yb, E]], ...edges];
      }
      ridge = [[x0 + h, Yr, Zr], [x1 - h, Yr, Zr]];
    } else {
      faces = [{p: [[x0, Yr, Zr], [x1, Yr, Zr], [x1, Yf, E2], [x0, Yf, E2]], main: true}];
      if (sk) faces.push({p: [[x0, Yf, E2], [x1, Yf, E2], [x1, Yo, E], [x0, Yo, E]], skirt: true});
      faces.push([[x0, Yo, E], [x1, Yo, E], [x1, Yo, E - th], [x0, Yo, E - th]]);
      knees = [Yr];
      if (runB > 0) {
        faces.push([[x0, Yr, Zr], [x1, Yr, Zr], [x1, Yb, E2], [x0, Yb, E2]]);
        if (sk) faces.push({p: [[x0, Yb, E2], [x1, Yb, E2], [x1, Ybo, E], [x0, Ybo, E]], skirt: true});
        faces.push([[x0, Ybo, E], [x1, Ybo, E], [x1, Ybo, E - th], [x0, Ybo, E - th]]);
        const prof = sk ? [[Ybo, E], [Yb, E2], [Yr, Zr], [Yf, E2], [Yo, E]] : [[Yb, E], [Yr, Zr], [Yf, E]];
        for (const x of [x0, x1]) {                       // the gable ends: the roof edge seen from the side
          faces.push([...prof.map(([y, z]) => [x, y, z]), ...prof.slice().reverse().map(([y, z]) => [x, y, z - th])]);
        }
        if (sk) knees = [Yf, Yr, Yb];
        ridge = [[x0, Yr, Zr], [x1, Yr, Zr]];
      } else {
        faces.push([[x0, Yr, Zr], [x1, Yr, Zr], [x1, Yr, Zr - th], [x0, Yr, Zr - th]]);
        for (const x of [x0, x1]) faces.push([[x, Yr, Zr], [x, Yf, E], [x, Yf, E - th], [x, Yr, Zr - th]]);
      }
    }
    top = Zr;
  }
  const mid = [(x0 + x1) / 2, (Yb + Yf) / 2, E - 6];
  ROOFGEO = {rt, Yr, Yf, Yb, Zr, zRoof, legs, top, ridge, hipY, knees, Yfront: Yo, Yback: Ybo,
             faces: faces.map((f) => {
               const pts = f.p || f;
               let n = norm(cross(sub(pts[1], pts[0]), sub(pts[2], pts[0])));
               const c = pts.reduce((s, q) => [s[0] + q[0] / pts.length, s[1] + q[1] / pts.length, s[2] + q[2] / pts.length], [0, 0, 0]);
               if (dot(n, sub(c, mid)) < 0) n = n.map((v) => -v);
               return {p: pts, n, slope: n[2] > 0.3 && n[1] > 0.2, main: !!f.main, skirt: !!f.skirt, wall: !!f.wall};
             })};
  HOUSE = {x0: x0 + 3, x1: x1 - 3, yb: Ybo + 3, yf: Yo - 3, zb: zRoof(Ybo + 3) - th, zf: zRoof(Yo - 3) - th};
  BOX = {x: WAGO.x + WAGO.w / 2 - 8, y: HOUSE.yf, w: 16, h: 5, z0: 12, z1: 30};
  // a lean-to porch over the door and windows, left of the control box and its cable
  ROOFGEO.porch = rt.porch ? {x0: HOUSE.x0 - 2, x1: HOUSE.x0 + 74, y0: HOUSE.yf, y1: HOUSE.yf + 18, zTop: 35, zLow: 28} : null;
  CENTER = [(HOUSE.x0 + HOUSE.x1) / 2, (HOUSE.yb + HOUSE.yf) / 2, Math.max(top, W([0, ROOF.y0, TOP])[2]) / 2];
  return ROOF_TYPE;
}
setRoof("pelana");

function project(p, cam) {
  const yaw = cam.yaw * Math.PI / 180, pitch = cam.pitch * Math.PI / 180;
  const x = p[0] - CENTER[0], y = p[1] - CENTER[1], z = p[2] - CENTER[2];
  const x1 = x * Math.cos(yaw) - y * Math.sin(yaw), y1 = x * Math.sin(yaw) + y * Math.cos(yaw);
  return [x1, y1 * Math.sin(pitch) - z * Math.cos(pitch), y1 * Math.cos(pitch) + z * Math.sin(pitch)];
}
/** Unit vector from the model towards the viewer: a face is visible when its outward normal points this way. */
function viewer(cam) {
  const yaw = cam.yaw * Math.PI / 180, pitch = cam.pitch * Math.PI / 180;
  return [Math.sin(yaw) * Math.cos(pitch), Math.cos(yaw) * Math.cos(pitch), Math.sin(pitch)];
}

/** The six faces of a box {x, y, w, h, z0, z1}: corner points and outward normal. */
function boxFaces(b) {
  const {x, y, w, h, z0, z1} = b, X = x + w, Y = y + h;
  return [
    {n: [0, 0, 1], p: [[x, y, z1], [X, y, z1], [X, Y, z1], [x, Y, z1]], top: true},
    {n: [0, 0, -1], p: [[x, y, z0], [x, Y, z0], [X, Y, z0], [X, y, z0]]},
    {n: [0, -1, 0], p: [[x, y, z0], [X, y, z0], [X, y, z1], [x, y, z1]]},
    {n: [0, 1, 0], p: [[x, Y, z0], [x, Y, z1], [X, Y, z1], [X, Y, z0]]},
    {n: [-1, 0, 0], p: [[x, y, z0], [x, y, z1], [x, Y, z1], [x, Y, z0]]},
    {n: [1, 0, 0], p: [[X, y, z0], [X, Y, z0], [X, Y, z1], [X, y, z1]]},
  ];
}
function panelBox(m) { const [ox, oy] = ORIGIN[m]; return {x: ox, y: oy, w: PANEL_W, h: PANEL_H, z0: RAIL, z1: TOP}; }
function panelCenter(m, z = TOP) { const [ox, oy] = ORIGIN[m]; return [ox + PANEL_W / 2, oy + PANEL_H / 2, z]; }
function cellQuad(m, c, r) {
  const [ox, oy] = ORIGIN[m], x = ox + FRAME + c * CELL_W, y = oy + FRAME + r * CELL_H, z = TOP + 0.02, g = 0.18;
  return [[x + g, y + g, z], [x + CELL_W - g, y + g, z], [x + CELL_W - g, y + CELL_H - g, z], [x + g, y + CELL_H - g, z]];
}

/** Back of one panel, as wired (docs/before/rangkaian/L1_panel_dioda_wago.png): terminal box at the bottom edge with
 * the bypass diode below it, and the cable under the array to this panel's slot on the Wago connector strip. */
function backParts(m) {
  const [ox, oy] = ORIGIN[m];
  const tb = {x: ox + PANEL_W / 2 - 4, y: oy + PANEL_H - 8, w: 8, h: 4.5, z0: 1.4, z1: RAIL - 0.1};
  const diode = {x: tb.x + 1.5, y: tb.y + tb.h + 0.7, w: 5, h: 1.3, z0: 1.6, z1: 2.6};
  const slot = WAGO.y + (PANELS.indexOf(m) + 0.5) * WAGO.h / 4;
  const ty = tb.y + tb.h / 2;
  const cable = [[tb.x + tb.w, ty, 2], [ARRAY_W + 2, ty, 0.6], [ARRAY_W + 2, slot, 0.6], [WAGO.x, slot, 1.2]];
  return {tb, diode, cable, slot: [WAGO.x + WAGO.w / 2, slot, WAGO.z1]};
}

/** A point on the roof surface itself (not on the panel plane) under roof coordinates (x, y): where cables lie. */
function onRoof(x, y) {
  const Y = W([x, y, 0])[1];
  return [x, Y, ROOFGEO.zRoof(Y) + 0.7];
}
const CABLE_OUT = 2.4;                                // the cable runs this far outside the array's edge

/** The cable loop, in world coordinates, which the flashes of light run in: two conductors leave the top of the control
 * box (the power), run up the front wall and over the eave, up the roof through the Wago strip, around the array (past
 * C, A, B and D, whose leads join it) and back down the wall into the box. */
function flashTrack() {
  const xw = WAGO.x + WAGO.w / 2, yIn = BOX.y + 1.2, o = CABLE_OUT;
  const wallTop = ROOFGEO.rt.hip ? EAVE - ROOF.t : HOUSE.zf;
  const Yedge = W([0, ROOF.y1, 0])[1], zEdge = ROOFGEO.zRoof(Yedge) + 0.7;
  const sk = ROOFGEO.rt.skirt;                        // a gambrel: over the outer eave, then up the steep band
  const up = (x) => (sk ? [[x, yIn, BOX.z1], [x, yIn, wallTop - 1], [x, ROOFGEO.Yfront + 0.8, EAVE + 0.7], [x, Yedge, zEdge],
                           onRoof(x, ROOF.y1 - 1)]
                        : [[x, yIn, BOX.z1], [x, yIn, wallTop - 1], [x, Yedge + 0.8, zEdge], onRoof(x, ROOF.y1 - 1)]);
  const go = up(xw - 1.2), back = up(xw + 1.2).reverse();
  return [...go, onRoof(xw - 1.2, WAGO.y + WAGO.h + 1), onRoof(xw - 1.2, WAGO.y - 1), onRoof(xw - 1.2, -o),
          onRoof(-o, -o), onRoof(-o, ARRAY_H + o), onRoof(xw + 1.2, ARRAY_H + o), ...back];
}
/** The short lead from the loop to each panel's frame (A and C on the ridge side, B and D on the eave side). */
function panelLeads() {
  const o = CABLE_OUT, mid = {A: PANEL_W / 2, B: PANEL_W / 2, C: PANEL_W + GAP + PANEL_W / 2, D: PANEL_W + GAP + PANEL_W / 2};
  return PANELS.map((m) => {
    const top = m === "A" || m === "C", y = top ? -o : ARRAY_H + o;
    return [onRoof(mid[m], y), W([mid[m], top ? 0.4 : ARRAY_H - 0.4, RAIL])];
  });
}
/** Point at arc length s along a polyline (and the polyline's total length). */
function along(track, s) {
  let left = s;
  for (let k = 0; k < track.length - 1; k++) {
    const a = track[k], b = track[k + 1], d = Math.hypot(...sub(b, a));
    if (left <= d) return a.map((v, j) => v + (b[j] - v) * (d ? left / d : 0));
    left -= d;
  }
  return track[track.length - 1].slice();
}
function trackLength(track) {
  let n = 0;
  for (let k = 0; k < track.length - 1; k++) n += Math.hypot(...sub(track[k + 1], track[k]));
  return n;
}

/** Shade of a face colour by its angle to the light (0.55 .. 1.0). */
function shade(n) { return 0.55 + 0.45 * Math.max(0, dot(n, LIGHT)); }
function mix(hex, k) {
  const c = parseInt(hex.slice(1), 16), f = (v) => Math.max(0, Math.min(255, Math.round(v * k)));
  return `rgb(${f(c >> 16)},${f((c >> 8) & 255)},${f(c & 255)})`;
}

const SUSUNAN_KATA = {"4S": "Seri (4S)", "2S2P": "Seri-paralel (2S2P)", "TCT": "Silang (TCT)", "4P": "Paralel (4P)"};
const COLOR = {normal: "#15803d", object: "#dc2626", diode: "#1d4ed8", cable: "#1d4ed8", nodata: "#94a3b8"};
const WORD = {normal: "Normal", object: "Cahaya tertutup", diode: "Masalah listrik", cable: "Masalah listrik",
              nodata: "Belum ada data"};

if (typeof module !== "undefined") {             // Node: unit tests (tests/test_twin_page.py)
  module.exports = {project, viewer, boxFaces, backParts, panelCenter, cellQuad, ORIGIN, PANEL_W, PANEL_H, ARRAY_W,
                    ARRAY_H, WAGO, HOME, COLOR, WORD, shade, dot, W, R, RAIL, TOP, ROOF, ROOF_TYPES, setRoof,
                    flashTrack, panelLeads, onRoof, along, trackLength, get HOUSE() { return HOUSE; }, get BOX() { return BOX; },
                    get ROOFGEO() { return ROOFGEO; }};
}

// ======================= page (browser only) =======================
if (typeof document !== "undefined") {
  const NS = "http://www.w3.org/2000/svg";
  const API = "/api/v1";
  const params = new URLSearchParams(location.search);
  const DEVICE = params.get("device_id") || "";
  const POS = {A: "kiri atas", B: "kiri bawah", C: "kanan atas", D: "kanan bawah"};
  const $ = (id) => document.getElementById(id);
  const svg = $("scene");

  let state = null, selected = null, seeThrough = false, anim = null, drag = null;
  const cam = {...HOME};
  let view = {cx: 0, cy: 0, half: 0};                // viewBox centre (projected) and half width

  // ---------- helpers ----------
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] !== undefined) e.setAttribute(k, attrs[k]);
    (parent || svg).appendChild(e);
    return e;
  }
  const PW = (p) => project(p, cam);                      // world point
  const P = (p) => project(W(p), cam);                     // roof point
  const ptsW = (list) => list.map((p) => { const q = PW(p); return `${q[0].toFixed(2)},${q[1].toFixed(2)}`; }).join(" ");
  const pts = (list) => ptsW(list.map(W));
  const id = (x, d = 2) => (x == null || Number.isNaN(+x) ? "-" : Number(x).toFixed(d).replace(".", ","));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  function jam(iso) {
    if (!iso) return "-";
    const t = new Date(iso);
    return t.toLocaleTimeString("id-ID", {hour: "2-digit", minute: "2-digit"});
  }
  function lalu(iso) {
    if (!iso) return "belum pernah";
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    if (s < 60) return "baru saja";
    if (s < 3600) return `${Math.round(s / 60)} menit lalu`;
    if (s < 86400) return `${Math.round(s / 3600)} jam lalu`;
    return `${Math.round(s / 86400)} hari lalu`;
  }
  async function api(path, opts) {
    const r = await fetch(API + path, {headers: {"Content-Type": "application/json"}, ...opts});
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }
  const K = () => (state && state.kondisi) || null;
  const panelState = (m) => ((K() && K().panels[m]) || {state: "nodata"});
  const problemOf = (m) => ((K() && K().problems) || []).find((p) => p.panel === m) || null;
  const sky = () => ((K() && K().problems) || []).find((p) => p.place === "sky" || p.place === "array") || null;

  // ---------- view box ----------
  function modelHalf() {
    const all = [[HOUSE.x0, HOUSE.yb, 0], [HOUSE.x1, HOUSE.yf, 0]];
    for (const x of [ROOF.x0, ROOF.x1]) for (const y of [ROOF.y0, ROOF.y1]) all.push(W([x, y, TOP]));
    return Math.max(...all.map((p) => Math.hypot(p[0] - CENTER[0], p[1] - CENTER[1], p[2] - CENTER[2]))) * 1.05;
  }
  const HALF_ALL = modelHalf();
  let MODEL_PTS = [], CORNER = [];                     // what the close view must show; the house's right front corner
  function modelPoints() {
    MODEL_PTS = [];
    for (const x of [-4, ARRAY_W + 4]) for (const y of [-4, ARRAY_H + 4]) MODEL_PTS.push(W([x, y, TOP]));
    for (const x of [BOX.x, BOX.x + BOX.w]) for (const z of [BOX.z0 - 6, BOX.z1]) MODEL_PTS.push([x, BOX.y + BOX.h, z]);
    const g = ROOFGEO;
    CORNER = [[ROOF.x1, g.Yfront, g.rt.flat ? g.Zr : EAVE], [HOUSE.x1, HOUSE.yf, BOX.z0 - 6]];
    MODEL_PTS.push(...CORNER);
  }
  function targetView() {
    if (!selected) {
      // Close view: the panels, the control box and the house's right corner, with a band at the top for the labels and
      // a margin of background on the right; any extra width opens to the left, into the roof and the wall.
      const aspect = (svg.clientWidth || 1000) / (svg.clientHeight || 640);
      const q = MODEL_PTS.map(PW), xs = q.map((p) => p[0]), ys = q.map((p) => p[1]);
      const x0 = Math.min(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      const right = Math.max(...CORNER.map((p) => PW(p)[0]));
      const band = (y1 - y0) * 0.1;                     // the labels sit over the roof, on white
      const halfH = (y1 - y0 + band) / 2 * 1.04;
      const half = Math.max((right - x0) / 2 * 1.3, halfH * aspect);
      return {cx: right + half * 0.3 - half, cy: (y0 - band + y1) / 2, half};
    }
    const c = P(panelCenter(selected, TOP));
    return {cx: c[0], cy: c[1], half: PANEL_W * 1.35};
  }
  function applyViewBox() {
    const w = svg.clientWidth || 1000, h = svg.clientHeight || 540;
    const halfH = view.half * h / w;
    svg.setAttribute("viewBox", `${view.cx - view.half} ${view.cy - halfH} ${2 * view.half} ${2 * halfH}`);
    return view.half * 2 / w;                       // viewBox units per screen pixel
  }

  // ---------- drawing ----------
  function defs() {
    const d = el("defs", {});
    const rad = (idv, color, a0) => {
      const g = el("radialGradient", {id: idv, cx: "50%", cy: "50%", r: "50%"}, d);
      el("stop", {offset: "0%", "stop-color": color, "stop-opacity": a0}, g);
      el("stop", {offset: "100%", "stop-color": color, "stop-opacity": 0}, g);
    };
    rad("gRed", "#dc2626", 0.7);
    rad("gBlue", "#1d4ed8", 0.85);
    const glass = el("linearGradient", {id: "gGlass", x1: "0", y1: "0", x2: "1", y2: "1"}, d);
    el("stop", {offset: "0%", "stop-color": "#ffffff", "stop-opacity": 0.22}, glass);
    el("stop", {offset: "45%", "stop-color": "#ffffff", "stop-opacity": 0.04}, glass);
    el("stop", {offset: "100%", "stop-color": "#ffffff", "stop-opacity": 0}, glass);
    const flash = el("radialGradient", {id: "gFlash", cx: "50%", cy: "50%", r: "50%"}, d);
    el("stop", {offset: "0%", "stop-color": "#fffbea", "stop-opacity": 1}, flash);
    el("stop", {offset: "35%", "stop-color": "#fde047", "stop-opacity": 0.85}, flash);
    el("stop", {offset: "100%", "stop-color": "#facc15", "stop-opacity": 0}, flash);
    const tailG = el("linearGradient", {id: "gTail", gradientUnits: "objectBoundingBox"}, d);
    el("stop", {offset: "0%", "stop-color": "#fef9c3", "stop-opacity": 0.95}, tailG);
    el("stop", {offset: "100%", "stop-color": "#facc15", "stop-opacity": 0.95}, tailG);
    const blur = el("filter", {id: "fBlur", x: "-50%", y: "-50%", width: "200%", height: "200%"}, d);
    el("feGaussianBlur", {stdDeviation: 2.2}, blur);
    const soft = el("filter", {id: "fSoft", x: "-50%", y: "-50%", width: "200%", height: "200%"}, d);
    el("feGaussianBlur", {stdDeviation: 0.8}, soft);
  }

  function solidBox(b, color, parent, opacity = 1, stroke = "none", world = false) {
    const w = viewer(cam);
    const faces = boxFaces(b).map((f) => (world ? f : {n: R(f.n), p: f.p.map(W)})).filter((f) => dot(f.n, w) > 0)
      .sort((a, c) => avgDepth(a.p) - avgDepth(c.p));
    for (const f of faces) {
      el("polygon", {points: ptsW(f.p), fill: mix(color, shade(f.n)), stroke, "stroke-width": 0.12, "fill-opacity": opacity,
                     "stroke-opacity": opacity}, parent);
    }
  }
  const avgDepth = (list) => list.reduce((s, p) => s + PW(p)[2], 0) / list.length;

  const TRIM = "#f4f1eb";                            // fascia, barge boards, window frames, porch posts
  const lerp3 = (a, b, s) => a.map((v, j) => v + (b[j] - v) * s);

  /** A window on a wall: frame, glass with a soft reflection, a cross of mullions and a sill. q: bottom-left,
   * bottom-right, top-right, top-left (world); n: the wall's outward normal; tone: the wall's light. */
  function windowOn(q, n, tone) {
    const Q = (u, v, k = 0) => lerp3(lerp3(q[0], q[1], u), lerp3(q[3], q[2], u), v).map((c, j) => c + n[j] * k);
    const poly = (list, attrs) => el("polygon", {points: ptsW(list), ...attrs});
    poly([Q(-0.07, -0.05, 0.08), Q(1.07, -0.05, 0.08), Q(1.07, 1.06, 0.08), Q(-0.07, 1.06, 0.08)],
         {fill: mix(TRIM, tone), stroke: mix("#cbd5e1", tone), "stroke-width": 0.12});
    poly([Q(0.08, 0.08, 0.1), Q(0.92, 0.08, 0.1), Q(0.92, 0.92, 0.1), Q(0.08, 0.92, 0.1)], {fill: mix("#8fb4d9", tone)});
    poly([Q(0.08, 0.5, 0.12), Q(0.5, 0.92, 0.12), Q(0.68, 0.92, 0.12), Q(0.08, 0.32, 0.12)], {fill: "#ffffff", opacity: 0.28});
    for (const [a, b] of [[Q(0.5, 0.08, 0.14), Q(0.5, 0.92, 0.14)], [Q(0.08, 0.5, 0.14), Q(0.92, 0.5, 0.14)]]) {
      el("polyline", {points: ptsW([a, b]), fill: "none", stroke: mix(TRIM, tone), "stroke-width": 0.55});
    }
    const s0 = Q(-0.12, -0.06, 0.08), s1 = Q(1.12, -0.06, 0.08), o0 = Q(-0.12, -0.06, 1.5), o1 = Q(1.12, -0.06, 1.5);
    const dn = (c) => [c[0], c[1], c[2] - 0.9];
    poly([s0, s1, o1, o0], {fill: mix(TRIM, Math.min(1, tone * 1.04))});
    poly([o0, o1, dn(o1), dn(o0)], {fill: mix(TRIM, tone * 0.82)});
  }

  /** The front door: trim, a wooden leaf with two panels, a handle, and a step in front. */
  function doorOn(q, n, tone) {
    const Q = (u, v, k = 0) => lerp3(lerp3(q[0], q[1], u), lerp3(q[3], q[2], u), v).map((c, j) => c + n[j] * k);
    const poly = (list, attrs) => el("polygon", {points: ptsW(list), ...attrs});
    poly([Q(-0.12, 0, 0.06), Q(1.12, 0, 0.06), Q(1.12, 1.05, 0.06), Q(-0.12, 1.05, 0.06)], {fill: mix(TRIM, tone)});
    poly([Q(0, 0, 0.1), Q(1, 0, 0.1), Q(1, 1, 0.1), Q(0, 1, 0.1)], {fill: mix("#8a6a4f", tone)});
    for (const [v0, v1] of [[0.1, 0.45], [0.55, 0.9]]) {
      poly([Q(0.16, v0, 0.12), Q(0.84, v0, 0.12), Q(0.84, v1, 0.12), Q(0.16, v1, 0.12)],
           {fill: mix("#9c7a5c", tone), stroke: mix("#6f523b", tone), "stroke-width": 0.12});
    }
    const h = PW(Q(0.84, 0.48, 0.3));
    el("circle", {cx: h[0], cy: h[1], r: 0.45, fill: "#e5e7eb", stroke: "#9ca3af", "stroke-width": 0.08});
  }

  /** The house: young grey walls with darker shaded sides, a plinth, framed windows, a wooden door, a soft shadow under the
   * eave; the roof of the chosen type with tiles, a ridge cap and white fascia; a gutter with a downpipe at the right
   * corner; a porch roof on posts for the kampung type; rack legs for a flat roof. World coordinates. Decoration only:
   * nothing here may look like an object shading a panel. */
  function drawHouse() {
    const {x0, x1, yb, yf} = HOUSE, g = ROOFGEO, w = viewer(cam), th = ROOF.t;
    const zt = (Y) => (g.rt.hip ? EAVE - th : g.zRoof(Y) - th);
    const side = (x) => {
      const p = [[x, yb, 0], [x, yf, 0], [x, yf, zt(yf)]];
      if (!g.rt.hip && !g.rt.flat) for (const Y of g.knees) if (Y > yb && Y < yf) p.push([x, Y, zt(Y)]);
      p.push([x, yb, zt(yb)]);
      return p;
    };
    const walls = [
      {n: [0, 1, 0], p: [[x0, yf, 0], [x1, yf, 0], [x1, yf, zt(yf)], [x0, yf, zt(yf)]], front: true},
      {n: [0, -1, 0], p: [[x1, yb, 0], [x0, yb, 0], [x0, yb, zt(yb)], [x1, yb, zt(yb)]]},
      {n: [-1, 0, 0], p: side(x0), side: x0},
      {n: [1, 0, 0], p: side(x1), side: x1},
    ].filter((f) => dot(f.n, w) > 0).sort((a, c) => avgDepth(a.p) - avgDepth(c.p));
    const wallTone = (n) => 0.8 + 0.2 * Math.max(0, dot(n, LIGHT));            // young grey front, darker sides
    const out = (p, n, k) => p.map((c, j) => c + n[j] * k);
    for (const f of walls) {
      const tone = wallTone(f.n);
      el("polygon", {points: ptsW(f.p), fill: mix(WALL_COLOR, tone), stroke: mix(WALL_COLOR, 0.86), "stroke-width": 0.2});
      const [a, b] = f.p;                                                         // plinth along the bottom
      el("polygon", {points: ptsW([out(a, f.n, 0.04), out(b, f.n, 0.04), out([b[0], b[1], 4], f.n, 0.04), out([a[0], a[1], 4], f.n, 0.04)]),
                     fill: mix(WALL_COLOR, tone * 0.84)});
      if (f.front) {
        const z = zt(yf);                                                         // soft shadow under the eave
        el("polygon", {points: ptsW([[x0, yf + 0.03, z - 6], [x1, yf + 0.03, z - 6], [x1, yf + 0.03, z], [x0, yf + 0.03, z]]),
                       fill: "#0f172a", opacity: 0.1, filter: "url(#fSoft)"});
        for (const [wa, wb] of [[x0 + 10, x0 + 24], [x0 + 30, x0 + 44]]) {
          windowOn([[wa, yf, 18], [wb, yf, 18], [wb, yf, 32], [wa, yf, 32]], f.n, tone);
        }
        doorOn([[x0 + 52, yf, 0], [x0 + 63, yf, 0], [x0 + 63, yf, 29], [x0 + 52, yf, 29]], f.n, tone);
        solidBox({x: x0 + 50, y: yf, w: 15, h: 4, z0: 0, z1: 1.4}, "#d6d3d1", null, 1, "#b9b4ae", true);
      } else if (f.side !== undefined) {
        const yA = yb + (yf - yb) * 0.4, yB = yb + (yf - yb) * 0.6, s = f.side === x0 ? -0.05 : 0.05;
        const q = f.side === x0 ? [[f.side + s, yA, 18], [f.side + s, yB, 18], [f.side + s, yB, 32], [f.side + s, yA, 32]]
          : [[f.side + s, yB, 18], [f.side + s, yA, 18], [f.side + s, yA, 32], [f.side + s, yB, 32]];
        windowOn(q, f.n, tone);
      }
    }
    // downpipe at the right front corner (drawn before the roof: the eave hangs over its top)
    if (!g.rt.flat) {
      const xp = x1 - 4, zg = EAVE - th - 1.4;
      solidBox({x: xp, y: yf + 0.2, w: 1.4, h: 1.4, z0: 1.6, z1: zg - 1}, "#d9dde3", null, 1, "#aeb5bf", true);
      solidBox({x: xp, y: yf + 0.2, w: 1.4, h: 3.2, z0: 0.3, z1: 1.6}, "#d9dde3", null, 1, "#aeb5bf", true);
    }
    const span = (Y) => {                                              // a hip roof narrows towards the ridge
      if (!g.rt.hip) return [ROOF.x0, ROOF.x1];
      const s = Math.max(0, Math.min(1, (g.Yf - Y) / (g.Yf - g.hipY)));
      return [ROOF.x0 + g.rt.hip * s, ROOF.x1 - g.rt.hip * s];
    };
    const faces = g.faces.filter((f) => dot(f.n, w) > 0).sort((a, c) => avgDepth(a.p) - avgDepth(c.p));
    for (const f of faces) {
      const lit = Math.max(0, dot(f.n, LIGHT)), upright = Math.abs(f.n[2]) < 0.05;
      const fill = f.wall ? mix(WALL_COLOR, wallTone(f.n)) : upright ? mix(TRIM, 0.82 + 0.18 * lit) : mix(ROOF_COLOR, 0.7 + 0.3 * lit);
      el("polygon", {points: ptsW(f.p), fill, stroke: f.wall || upright ? "#c9ced6" : mix(ROOF_COLOR, 0.82), "stroke-width": 0.2,
                     "stroke-linejoin": "round"});
      if (f.main && !g.rt.flat) {                                     // tiles: rows with staggered joints
        let d = "";
        const seg = (a, b) => { const p = PW(a), q = PW(b); d += `M${p[0].toFixed(2)} ${p[1].toFixed(2)}L${q[0].toFixed(2)} ${q[1].toFixed(2)}`; };
        for (let y = ROOF.y0 + 4, row = 0; y <= ROOF.y1 + 1e-6; y += 4, row++) {
          const Y = W([0, y, 0])[1], Y0 = W([0, y - 4, 0])[1], z = g.zRoof(Y) + 0.03, z0 = g.zRoof(Y0) + 0.03;
          const [xa, xb] = span(Y), [xa0, xb0] = span(Y0);
          if (y < ROOF.y1 - 1e-6) seg([xa, Y, z], [xb, Y, z]);
          for (let x = xa0 + (row % 2 ? 3 : 6); x < xb0 - 1; x += 6) seg([x, Y0, z0], [x, Y, z]);
        }
        el("path", {d, fill: "none", stroke: mix(ROOF_COLOR, 0.86), "stroke-width": 0.16});
      }
      if (f.skirt) {
        const front = f.n[1] > 0, Ya = front ? g.Yf : g.Yb, Yz = front ? g.Yfront : g.Yback;
        for (const k of [0.25, 0.5, 0.75]) {
          const Y = Ya + (Yz - Ya) * k, z = g.zRoof(Y) + 0.03;
          el("polyline", {points: ptsW([[ROOF.x0, Y, z], [ROOF.x1, Y, z]]), fill: "none", stroke: mix(ROOF_COLOR, 0.86), "stroke-width": 0.18});
        }
      }
    }
    if (g.ridge) {                                                    // ridge cap
      el("polyline", {points: ptsW(g.ridge), fill: "none", stroke: mix(ROOF_COLOR, 0.72), "stroke-width": 1.1, "stroke-linecap": "round"});
    }
    if (!g.rt.flat) {                                                 // gutter along the front eave, and its outlet
      const zg = EAVE - th - 1.4;
      solidBox({x: ROOF.x0, y: g.Yfront + 0.1, w: ROOF.x1 - ROOF.x0, h: 1.5, z0: zg, z1: zg + 1.6}, "#d9dde3", null, 1, "#aeb5bf", true);
      solidBox({x: x1 - 4, y: yf + 0.2, w: 1.4, h: g.Yfront + 0.6 - yf, z0: zg - 1.2, z1: zg}, "#d9dde3", null, 1, "#aeb5bf", true);
    }
    const pr = g.porch;
    if (pr) {                                                         // kampung: a porch roof on posts over the door
      for (const x of [pr.x0 + 1, (pr.x0 + pr.x1) / 2, pr.x1 - 2.6]) {
        solidBox({x, y: pr.y1 - 2.2, w: 1.6, h: 1.6, z0: 0, z1: pr.zLow - 1.4}, TRIM, null, 1, "#c9ced6", true);
      }
      const t1 = 1.4, pf = [
        {n: [0, 1, 0], p: [[pr.x0, pr.y1, pr.zLow], [pr.x1, pr.y1, pr.zLow], [pr.x1, pr.y1, pr.zLow - t1], [pr.x0, pr.y1, pr.zLow - t1]], trim: true},
        {n: [-1, 0, 0], p: [[pr.x0, pr.y0, pr.zTop], [pr.x0, pr.y1, pr.zLow], [pr.x0, pr.y1, pr.zLow - t1], [pr.x0, pr.y0, pr.zTop - t1]], trim: true},
        {n: [1, 0, 0], p: [[pr.x1, pr.y0, pr.zTop], [pr.x1, pr.y1, pr.zLow], [pr.x1, pr.y1, pr.zLow - t1], [pr.x1, pr.y0, pr.zTop - t1]], trim: true},
        {n: norm([0, pr.zTop - pr.zLow, pr.y1 - pr.y0]), p: [[pr.x0, pr.y0, pr.zTop], [pr.x1, pr.y0, pr.zTop], [pr.x1, pr.y1, pr.zLow], [pr.x0, pr.y1, pr.zLow]]},
      ].filter((f) => dot(f.n, w) > 0).sort((a, c) => avgDepth(a.p) - avgDepth(c.p));
      for (const f of pf) {
        const lit = Math.max(0, dot(f.n, LIGHT));
        el("polygon", {points: ptsW(f.p), fill: f.trim ? mix(TRIM, 0.82 + 0.18 * lit) : mix(ROOF_COLOR, 0.7 + 0.3 * lit),
                       stroke: f.trim ? "#c9ced6" : mix(ROOF_COLOR, 0.82), "stroke-width": 0.2});
        if (!f.trim) {
          for (let k = 1; k < 4; k++) {
            const y = pr.y0 + (pr.y1 - pr.y0) * k / 4, z = pr.zTop + (pr.zLow - pr.zTop) * k / 4 + 0.03;
            el("polyline", {points: ptsW([[pr.x0, y, z], [pr.x1, y, z]]), fill: "none", stroke: mix(ROOF_COLOR, 0.86), "stroke-width": 0.18});
          }
        }
      }
    }
    for (const [a, b] of g.legs) {                                    // rack legs on a flat roof
      el("polyline", {points: ptsW([a, b]), fill: "none", stroke: "#9ca3af", "stroke-width": 0.7});
    }
  }

  /** The cables the flashes run in: dark insulation with a light sheen, and the leads to each panel. */
  function drawCables() {
    for (const path of [flashTrack(), ...panelLeads()]) {
      el("polyline", {points: ptsW(path), fill: "none", stroke: "#2b2f36", "stroke-width": 0.85, "stroke-linecap": "round",
                      "stroke-linejoin": "round"});
      el("polyline", {points: ptsW(path), fill: "none", stroke: "#8a919c", "stroke-width": 0.22, opacity: 0.7,
                      "stroke-linecap": "round", "stroke-linejoin": "round"});
    }
  }

  /** Flashes of light running the loop: a new one leaves the control box when the newest is half way round. */
  let flashes = [], flashT = null;
  function flashFrame(now) {
    const grp = document.getElementById("flashes");
    if (grp) grp.textContent = "";
    const dt = flashT === null ? 0 : Math.min(0.1, (now - flashT) / 1000);
    flashT = now;
    if (!grp || selected || !flowOn() || drag) { flashes = []; requestAnimationFrame(flashFrame); return; }
    const track = flashTrack(), total = trackLength(track), speed = total / 3.6, tail = 16;
    if (!flashes.length || flashes[flashes.length - 1].s >= total / 2) flashes.push({s: 0});
    for (const f of flashes) f.s += speed * dt;
    flashes = flashes.filter((f) => f.s - tail <= total);
    for (const f of flashes) {
      const head = Math.min(f.s, total), pts3 = [];
      for (let k = 0; k <= 8; k++) pts3.push(along(track, Math.max(0, head - tail * (1 - k / 8))));
      const line = ptsW(pts3);
      el("polyline", {points: line, fill: "none", stroke: "#fde047", "stroke-width": 3.4, opacity: 0.45,
                      "stroke-linecap": "round", "stroke-linejoin": "round", filter: "url(#fSoft)"}, grp);
      el("polyline", {points: line, fill: "none", stroke: "url(#gTail)", "stroke-width": 1.3, "stroke-linecap": "round",
                      "stroke-linejoin": "round"}, grp);
      if (f.s <= total) {
        const q = PW(along(track, head));
        el("circle", {cx: q[0], cy: q[1], r: 3.2, fill: "url(#gFlash)"}, grp);
      }
    }
    requestAnimationFrame(flashFrame);
  }
  requestAnimationFrame(flashFrame);

  function flowOn() {
    const k = K(), mon = (state && state.monitor) || {};
    if (!k || !mon.on || k.status.level === "offline" || !k.array || !(k.array.pmax_w > 0)) return false;
    const age = (Date.now() - Date.parse(k.array.at)) / 1000;
    return age < Math.max(600, 2.5 * (mon.array_interval_s || 300));
  }

  /** How dark a panel is drawn: the share of light it lost. A blocked panel by its power against the best panel; with
   * less light everywhere (cloud or dust) all panels by the array's power against normal. A small blockage gives a light
   * shade, a large one a deep shade; the whole panel, since where on its surface is not measurable. */
  function darkness(m) {
    const ps = panelState(m), k = K();
    if (ps.state === "object") return Math.min(0.8, 0.18 + 0.62 * (1 - (ps.power_rel != null ? ps.power_rel : 0.5)));
    const s = sky(), pct = k && k.array && k.array.pct_of_expected;
    if (s && pct != null && pct < 100) return Math.min(0.7, 0.12 + 0.6 * (1 - pct / 100));
    return 0;
  }

  function drawPanel(m, translucent) {
    const st = panelState(m).state, sel = selected === m;
    const g = el("g", {"data-m": m, opacity: translucent ? 0.32 : 1, style: "cursor:pointer"});
    solidBox(panelBox(m), "#c9d1db", g, 1, "#94a3b8");                      // aluminium frame
    const [ox, oy] = ORIGIN[m];
    const glassPts = [[ox + FRAME * 0.6, oy + FRAME * 0.6, TOP + 0.01], [ox + PANEL_W - FRAME * 0.6, oy + FRAME * 0.6, TOP + 0.01],
                      [ox + PANEL_W - FRAME * 0.6, oy + PANEL_H - FRAME * 0.6, TOP + 0.01], [ox + FRAME * 0.6, oy + PANEL_H - FRAME * 0.6, TOP + 0.01]];
    el("polygon", {points: pts(glassPts), fill: "#e8edf3"}, g);              // white backsheet between cells
    for (let c = 0; c < COLS; c++) for (let r = 0; r < ROWS; r++) {
      el("polygon", {points: pts(cellQuad(m, c, r)), fill: (c + r) % 2 ? "#1c3253" : "#1f3759"}, g);
    }
    el("polygon", {points: pts(glassPts), fill: "url(#gGlass)"}, g);
    const dim = translucent ? 0 : darkness(m);                                 // light that does not reach the cells
    if (dim) el("polygon", {points: pts(glassPts), fill: "#0b1220", "fill-opacity": dim}, g);
    if (st === "object" && !translucent) {
      el("polygon", {points: pts(glassPts), fill: "url(#gRed)", class: "pulse"}, g);
    }
    if (sel) el("polygon", {points: pts(boxFaces(panelBox(m))[0].p), fill: "none", stroke: "#1d4ed8", "stroke-width": 0.5}, g);
    return g;
  }

  function drawBack(translucentFor) {
    // Under the panels: terminal boxes, diodes, cables (only visible through see-through panels), then the Wago strip.
    for (const m of PANELS) {
      const {tb, diode, cable} = backParts(m);
      const hot = translucentFor && translucentFor.panel === m;
      el("polyline", {points: pts(cable), fill: "none", stroke: "#111827", "stroke-width": 0.55, "stroke-linejoin": "round", opacity: 0.85});
      solidBox(tb, hot && translucentFor.place === "diode" ? "#1d4ed8" : "#374151", null);
      solidBox(diode, "#111827", null);
    }
  }

  function drawWago() {
    solidBox(WAGO, "#e5e7eb", null, 1, "#9ca3af");
    for (let k = 0; k < 4; k++) {
      const y = WAGO.y + (k + 0.5) * WAGO.h / 4;
      solidBox({x: WAGO.x + 0.6, y: y - 1.6, w: 1.6, h: 3.2, z0: WAGO.z1, z1: WAGO.z1 + 0.8}, "#f97316", null);
    }
  }
  function drawControlBox() {
    solidBox(BOX, "#767676", null, 1, "#5b5b5b", true);
    const y = BOX.y + BOX.h + 0.02;                              // its front: a small display window
    el("polygon", {points: ptsW([[BOX.x + 3, y, BOX.z1 - 4], [BOX.x + BOX.w - 3, y, BOX.z1 - 4], [BOX.x + BOX.w - 3, y, BOX.z1 - 9],
                                 [BOX.x + 3, y, BOX.z1 - 9]]), fill: "#a3adb8"});
  }

  function glowAt(p, r) {
    const q = P(p);
    el("circle", {cx: q[0], cy: q[1], r, fill: "url(#gBlue)", class: "pulse"});
  }

  let fontPx = 1;
  /** Tesla-style callouts: a dot on the part, a leader line, a value and a small caption. Labels above the model for
   * anchors in its upper half, below for the lower half; within a band they are pushed apart so none overlap. */
  function layoutCallouts(items, top, bottom, left, right) {
    for (const it of items) {
      it.w = Math.max(it.big.length * 0.62 * 1.15, it.small.length * 0.66 * 0.72) * fontPx + fontPx;
      it.a = it.world ? PW(it.anchor) : P(it.anchor);
    }
    const mid = Infinity;                              // every part is on the roof: one band of labels above the model
    for (const band of [items.filter((i) => i.a[1] < mid), items.filter((i) => i.a[1] >= mid)]) {
      band.sort((p, q) => p.a[0] - q.a[0]);
      let x = -Infinity;
      for (const it of band) { it.x = Math.max(it.a[0], x === -Infinity ? left + it.w / 2 : x + it.w / 2); x = it.x + it.w / 2 + fontPx * 0.8; }
      let over = band.length ? band[band.length - 1].x + band[band.length - 1].w / 2 - right : 0;
      for (let k = band.length - 1; k >= 0 && over > 0; k--) {
        band[k].x -= over;
        over = k > 0 ? (band[k - 1].x + band[k - 1].w / 2 + fontPx * 0.8) - (band[k].x - band[k].w / 2) : 0;
      }
      for (const it of band) it.y = it.a[1] < mid ? top : bottom;
    }
    for (const it of items) {
      const up = it.y < it.a[1], yEnd = up ? it.y + fontPx * 2.5 : it.y - fontPx * 0.3, yKnee = up ? yEnd + fontPx * 0.8 : yEnd - fontPx * 0.8;
      el("polyline", {points: `${it.a[0]},${it.a[1]} ${it.a[0]},${yKnee} ${it.x},${yEnd}`, fill: "none", stroke: "#64748b",
                      "stroke-width": fontPx * 0.06});
      el("circle", {cx: it.a[0], cy: it.a[1], r: fontPx * 0.24, fill: "#334155"});
      el("rect", {x: it.x - it.w / 2, y: it.y - fontPx * 0.05, width: it.w, height: fontPx * 2.45, rx: fontPx * 0.35,
                  fill: "#ffffff", opacity: 0.92});                // readable over the roof
      const b = el("text", {x: it.x, y: it.y + fontPx * 1.0, class: "lbl", "font-size": fontPx * 1.15, "font-weight": 650,
                            "text-anchor": "middle", fill: it.color || "#0f172a"});
      b.textContent = it.big;
      const s = el("text", {x: it.x, y: it.y + fontPx * 2.1, class: "lbl small", "font-size": fontPx * 0.72, "text-anchor": "middle"});
      s.textContent = it.small;
    }
  }

  function draw() {
    svg.textContent = "";
    const perPx = applyViewBox();
    fontPx = 13 * perPx;
    defs();
    const k = K();
    const focusProblem = selected ? problemOf(selected) : null;
    const behind = seeThrough || (focusProblem && (focusProblem.place === "diode" || focusProblem.place === "cable"));
    // ground and the house's soft shadow
    const g0 = 18;
    el("polygon", {points: ptsW([[HOUSE.x0 - g0, HOUSE.yb - g0, 0], [HOUSE.x1 + g0, HOUSE.yb - g0, 0], [HOUSE.x1 + g0, HOUSE.yf + g0 * 1.6, 0],
                                 [HOUSE.x0 - g0, HOUSE.yf + g0 * 1.6, 0]]), fill: "#eef2f5"});
    el("polygon", {points: ptsW([[HOUSE.x0 - 2, HOUSE.yb - 2, 0], [HOUSE.x1 + 6, HOUSE.yb - 2, 0], [HOUSE.x1 + 8, HOUSE.yf + 8, 0],
                                 [HOUSE.x0 + 2, HOUSE.yf + 8, 0]]), fill: "#0f172a", opacity: 0.1, filter: "url(#fBlur)"});
    drawHouse();
    drawControlBox();
    drawCables();
    drawBack(focusProblem);
    drawWago();
    // panels, far ones first
    const order = [...PANELS].sort((a, b) => P(panelCenter(a))[2] - P(panelCenter(b))[2]);
    for (const m of order) {
      const own = problemOf(m), under = own && (own.place === "diode" || own.place === "cable");
      drawPanel(m, seeThrough || (behind && selected === m) || (!selected && under));
    }
    // problems that live behind or beside the panels
    for (const p of (k && k.problems) || []) {
      if (!p.panel) continue;
      if (selected && selected !== p.panel) continue;
      const parts = backParts(p.panel);
      if (p.place === "diode") glowAt([parts.diode.x + parts.diode.w / 2, parts.diode.y, -1], selected ? 7 : 9);
      if (p.place === "cable") {
        el("polyline", {points: pts(parts.cable), fill: "none", stroke: "#1d4ed8", "stroke-width": selected ? 2.2 : 3,
                        opacity: 0.45, filter: "url(#fBlur)", class: "pulse"});
        el("polyline", {points: pts(parts.cable), fill: "none", stroke: "#1d4ed8", "stroke-width": 0.6});
        glowAt(parts.slot, selected ? 5 : 7);
        glowAt([parts.tb.x + parts.tb.w, parts.tb.y + parts.tb.h / 2, -1], selected ? 5 : 7);
      }
    }
    el("g", {id: "flashes"});                          // filled every frame by flashFrame()
    // callouts
    const items = [];
    for (const m of (selected ? [selected] : PANELS)) items.push(panelCallout(m));
    if (!selected && k && k.array) {
      const a = k.array;
      items.push({anchor: W([WAGO.x + WAGO.w / 2, ROOF.y1, 0]), world: true, big: `${id(a.pmax_w, 2)} W`,
                  small: "Daya semua panel" + (a.pct_of_expected != null ? `, ${Math.round(a.pct_of_expected)} persen dari normal` : "")});
    }
    const h = view.half * (svg.clientHeight / (svg.clientWidth || 1));
    layoutCallouts(items, view.cy - h + fontPx * 0.8, view.cy + h - fontPx * 2.8, view.cx - view.half + fontPx, view.cx + view.half - fontPx);
  }

  function panelCallout(m) {
    const ps = panelState(m);
    const big = ps.state === "nodata" ? "Belum ada data" : `${id(ps.pmax_w, 2)} W`;
    const small = `Panel ${m}` + (ps.power_rel != null ? `, ${Math.round(ps.power_rel * 100)} persen` : "") +
                  (ps.state !== "nodata" ? `, ${WORD[ps.state].toLowerCase()}` : "");
    return {anchor: panelCenter(m, TOP + 0.3), big, small, color: ps.state === "normal" ? "#0f172a" : COLOR[ps.state]};
  }

  // ---------- cards and rows ----------
  /** Embedded in the dashboard (Beranda): no scrollbar of its own; the page's height goes to the dashboard, which sizes
   * the frame so the main page scrolls instead. Sent after every render (the dashboard may start listening late). */
  const EMBEDDED = window.parent !== window;
  if (EMBEDDED) document.documentElement.style.overflow = "hidden";
  function postHeight() {
    if (!EMBEDDED) return;
    const w = document.querySelector(".wrap");
    window.parent.postMessage({type: "shadeshift-tinggi", h: Math.ceil(w.getBoundingClientRect().bottom + window.scrollY + 24)}, "*");
  }

  function render() {
    draw();
    const k = K();
    $("demo").hidden = !(k && k.demo);
    const st = $("status");
    if (k) {
      const place = (k.problems[0] || {}).place;
      const tone = place === "diode" || place === "cable" ? " elec" : place === "sky" || place === "array" ? " sky" : "";
      st.className = `status ${k.status.level}${tone}`;
      st.textContent = k.status.text;
      $("meta").textContent = k.last_check ? `Pemeriksaan panel terakhir ${lalu(k.last_check)}` : "";
    }
    $("back").hidden = !selected;
    $("behind").textContent = seeThrough ? "Tampilkan bagian depan" : "Lihat bagian belakang";
    renderPerawatan();
    renderCards();
    renderRows();
    postHeight();
  }

  /** Predictive maintenance under the stage (CONTRACT §28): what will need attention and roughly when, the log, and the
   * owner's buttons to record cleaning or a repair (a fresh baseline starts there). */
  function renderPerawatan() {
    const pw = state && state.perawatan, box = $("rawat");
    if (!pw) { box.innerHTML = ""; return; }
    const kapan = (p) => p.hari === null ? "Berulang" : p.hari <= 0 ? "Sekarang" : `Sekitar ${Math.max(1, Math.round(p.hari))} hari lagi`;
    let html = `<div class="top"><h2>Perawatan</h2><span class="meta">Perkiraan dari kebiasaan panel 14 hari terakhir</span></div>` +
      `<p class="sum ${esc(pw.ringkas.level)}">${esc(pw.ringkas.text)}</p>`;
    for (const p of pw.prediksi) {
      html += `<div class="item"><span class="when">${kapan(p)}</span><b>${esc(p.judul)}</b><span>${esc(p.kalimat)}</span></div>`;
    }
    for (const c of pw.log.slice(0, 3)) html += `<p class="log">${esc(c.teks)}${c.efek ? " " + esc(c.efek) : ""}</p>`;
    if (pw.demo) html += `<p class="log" style="color:#92400e">Data demo: perkiraan dari kurva lab yang direkam, bukan pengukuran saat ini.</p>`;
    html += `<div class="acts"><button class="btn" id="rawatBersih">Saya sudah membersihkan panel</button>` +
      `<button class="btn" id="rawatPerbaikan">Panel sudah diperbaiki teknisi</button></div>`;
    box.innerHTML = html;
    const log = (jenis) => api(`/devices/${encodeURIComponent(DEVICE)}/perawatan`, {method: "POST", body: JSON.stringify({jenis})})
      .then(() => { $("err").textContent = ""; setTimeout(load, 800); })
      .catch((e) => { $("err").textContent = "Catatan perawatan gagal disimpan: " + e.message; });
    $("rawatBersih").onclick = () => log("bersih");
    $("rawatPerbaikan").onclick = () => log("perbaikan");
  }

  function problemCard(p) {
    const cls = p.place === "diode" || p.place === "cable" ? "problem elec" : p.panel ? "problem" : "problem grey";
    return `<div class="card ${cls}"><h2>${esc(p.title)}</h2><dl>` +
      `<dt>Lokasi</dt><dd>${esc(p.where)}</dd><dt>Besarnya</dt><dd>${esc(p.how_much)}</dd>` +
      (p.since ? `<dt>Sejak</dt><dd>pukul ${jam(p.since)}</dd>` : "") +
      `<dt>Saran</dt><dd>${esc(p.advice)}</dd></dl>` +
      (p.panel && selected !== p.panel ? `<button class="btn" data-sel="${p.panel}">Lihat panel ${p.panel}</button>` : "") + `</div>`;
  }

  function renderCards() {
    const k = K(), box = $("cards");
    if (!k) { box.innerHTML = ""; return; }
    let html = "";
    if (selected) {
      const ps = panelState(selected), lt = (state.latest || {})[selected] || {};
      html += `<div class="card"><div class="panelhead"><h2>Panel ${selected} (${POS[selected]})</h2>` +
        `<span style="color:${COLOR[ps.state]};font-weight:600">${WORD[ps.state]}</span></div>` +
        (ps.state === "nodata" ? `<p class="note">Panel ini belum pernah diperiksa sendiri. Mulai pemantauan agar setiap panel diperiksa.</p>` :
        `<div class="kv"><div><b>${id(ps.pmax_w, 3)} W</b><span>Daya maksimum</span></div>` +
        `<div><b>${Math.round(ps.power_rel * 100)} persen</b><span>Dibanding panel terbaik</span></div>` +
        `<div><b>${id(lt.voc, 2)} V</b><span>Tegangan tanpa beban</span></div>` +
        `<div><b>${lt.isc != null ? id(lt.isc * 1000, 1) : "-"} mA</b><span>Arus hubung singkat</span></div></div>` +
        `<p class="note">Diperiksa ${lalu(ps.at)}, pukul ${jam(ps.at)}.</p>`) + `</div>`;
      const p = problemOf(selected);
      if (p) html += problemCard(p);
    } else if (k.problems.length) {
      html += k.problems.map(problemCard).join("");
    } else if (k.status.level === "ok") {
      html += `<div class="card"><h2>Semua panel normal</h2><p class="note">Tidak ada panel yang dayanya turun dibanding panel lain` +
        (k.last_check ? `, pemeriksaan terakhir pukul ${jam(k.last_check)}.` : ".") + `</p></div>`;
    }
    if (k.problems.length) html += `<p class="note" style="margin:0;color:var(--muted);font-size:12px">${esc(k.rules)}</p>`;
    if (k.demo) html += `<p class="note" style="margin:0;color:#92400e;font-size:12px">Data demo: kurva lab yang direkam dan model kembaran untuk panel tunggal, bukan pengukuran saat ini.</p>`;
    box.innerHTML = html;
    for (const b of box.querySelectorAll("[data-sel]")) b.onclick = () => select(b.dataset.sel);
  }

  /** The selector's recommendation (CONTRACT §21): computed on the ESP32 with firmware 3.x, on the laptop in demo mode. */
  function aiRow() {
    const ai = state && state.ai, n = ai && ai.now;
    if (!n) return "";
    const demo = ai.device_kind === "emulator";
    const where = n.on_esp32 ? "di ESP32" : demo ? "di laptop (mode demo: ESP32 tiruan tidak menjalankan AI)"
      : (ai.esp32 && ai.esp32.weights) ? "di laptop" : "di laptop (firmware ESP32 belum memuat model AI)";
    const ms = n.latency_us ? ` dalam ${id(n.latency_us / 1000, 2)} ms` : "";
    const nama = SUSUNAN_KATA[n.choice] || n.choice;
    const note = ai.wiring === n.choice ? "Rangkaian sekarang sudah sesuai saran." : "Rangkaian tidak diubah otomatis.";
    return `<div class="row"><div><div class="t">${n.on_esp32 ? "Saran AI di ESP32 (TinyML)" : "Saran AI"}</div>` +
      `<div class="s">Cara merangkai panel yang paling cocok untuk kondisi sekarang, dari pengukuran pukul ${jam(n.captured_at)}, ` +
      `dihitung ${where}${ms}. ${note}</div></div><div class="t">${esc(nama)}</div></div>`;
  }

  /** The diagnosis AI on the ESP32 (CONTRACT §23): the cause of the whole array from four wirings, or why it cannot run. */
  function diagRow() {
    const g = state && state.diag;
    if (!g) return "";
    const n = g.now, f = g.failed, cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
    let s;
    if (n) {
      const yakin = n.confidence != null ? `, keyakinan ${Math.round(n.confidence * 100)} persen` : "";
      const ms = n.t_us ? `, dihitung di ESP32 dalam ${id(n.t_us / 1000, 1)} ms` : "";
      s = `Penyebab gangguan menurut AI, dari pengukuran dengan empat cara merangkai panel ${lalu(n.at)} (pukul ${jam(n.at)})${yakin}${ms}. ` +
        "AI menilai semua panel bersama; panel yang terdampak terlihat dari pemeriksaan tiap panel.";
    } else {
      s = g.why ? cap(g.why) : "Belum dijalankan. ESP32 mengukur panel dengan empat cara merangkai, lalu menilai penyebab gangguan.";
    }
    if (f && (!n || f.at > n.at)) s += ` Percobaan terakhir pukul ${jam(f.at)} gagal: ${esc(f.text)}.`;
    const val = n ? n.nama : g.on_board === false ? "Belum dipasang" : g.device_kind === "emulator" ? "Tidak berjalan" : "-";
    return `<div class="row"><div><div class="t">Diagnosis AI di ESP32</div><div class="s">${s}</div></div>` +
      `<div style="text-align:right"><div class="t">${esc(val)}</div>` +
      (g.available ? `<button class="btn" id="diagrun" style="margin-top:6px">Diagnosis dengan AI</button>` : "") + `</div></div>`;
  }

  function renderRows() {
    const k = K(), box = $("rows");
    if (!k) { box.innerHTML = ""; return; }
    const a = k.array, mon = state.monitor || {on: false};
    box.innerHTML =
      `<div class="row"><div><div class="t">Daya semua panel</div><div class="s">${a ? `Diukur ${lalu(a.at)}, panel dirangkai ${SUSUNAN_KATA[a.topology] || a.topology}` : "Belum ada pengukuran"}</div></div>` +
      `<div class="t">${a ? `${id(a.pmax_w, 3)} W` : "-"}</div></div>` +
      aiRow() + diagRow() +
      `<div class="row"><div><div class="t">Perkiraan normal</div><div class="s">Daya yang diharapkan bila panel bersih dan tidak terhalang (perkiraan, meleset sekitar 8 persen pada uji lab)</div></div>` +
      `<div class="t">${a && a.expected_w ? `${id(a.expected_w, 3)} W` : "-"}</div></div>` +
      `<div class="row"><div><div class="t">Pemantauan</div><div class="s">${mon.on ? `Aktif: panel diukur setiap ${Math.round(mon.array_interval_s / 60)} menit` +
        (mon.panels ? `, setiap panel diperiksa setiap ${Math.round(mon.panel_interval_s / 60)} menit` : "") : "Tidak aktif"}</div></div>` +
      `<div>${mon.on ? `<button class="btn" id="monstop">Hentikan pemantauan</button>` : `<button class="btn primary" id="monstart">Mulai pemantauan</button>`}</div></div>`;
    const demo = state.demo;
    if (demo && (demo.available_conditions || []).length) {
      box.innerHTML += `<div class="row"><div><div class="t">Rekaman lab yang diputar (mode demo)</div>` +
        `<div class="s">Memilih kondisi bayangan dari data lab. Panel diperiksa ulang sesudahnya.</div></div>` +
        `<div><select id="democond" class="btn">${demo.available_conditions.map((c) => `<option${c === demo.condition ? " selected" : ""}>${esc(c)}</option>`).join("")}</select> ` +
        `<button class="btn" id="demoapply">Terapkan</button></div></div>`;
    }
    const send = (cmd, params) => api(`/devices/${encodeURIComponent(DEVICE)}/commands`,
      {method: "POST", body: JSON.stringify({kind: "action", command: cmd, params: params || {}})});
    const fail = (e) => { $("err").textContent = "Perintah gagal: " + e.message; };
    const go = (cmd) => send(cmd).then(() => setTimeout(load, 1200)).catch(fail);
    if ($("monstart")) $("monstart").onclick = () => go("monitor_start");
    if ($("monstop")) $("monstop").onclick = () => go("monitor_stop");
    if ($("diagrun")) $("diagrun").onclick = () => go("diagnose");
    if ($("demoapply")) $("demoapply").onclick = async () => {
      try {
        await send("demo_condition", {condition: $("democond").value});
        await send("panel_check");         // with monitoring on, the monitoring loop checks the panels now
        $("err").textContent = "";
        setTimeout(load, 4000);
      } catch (e) { fail(e); }
    };
  }

  // ---------- camera moves ----------
  function animateTo(to, ms = 650) {
    const from = {yaw: cam.yaw, pitch: cam.pitch, ...view};
    const t0 = performance.now();
    if (anim) cancelAnimationFrame(anim);
    const step = (now) => {
      const t = Math.min(1, (now - t0) / ms), e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
      cam.yaw = from.yaw + (to.yaw - from.yaw) * e;
      cam.pitch = from.pitch + (to.pitch - from.pitch) * e;
      const tv = targetView();
      view = {cx: from.cx + (tv.cx - from.cx) * e, cy: from.cy + (tv.cy - from.cy) * e, half: from.half + (tv.half - from.half) * e};
      draw();
      anim = t < 1 ? requestAnimationFrame(step) : null;
    };
    anim = requestAnimationFrame(step);
  }
  function select(m) {
    selected = m;
    render();
    animateTo(m ? {yaw: cam.yaw, pitch: Math.max(30, Math.min(55, cam.pitch))} : {...HOME});
  }

  // ---------- input: drag to rotate, click a panel ----------
  svg.addEventListener("pointerdown", (ev) => {
    drag = {x: ev.clientX, y: ev.clientY, yaw: cam.yaw, pitch: cam.pitch, moved: false, target: ev.target};
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    svg.classList.add("dragging");
    cam.yaw = drag.yaw - dx * 0.35;
    cam.pitch = Math.max(12, Math.min(89, drag.pitch + dy * 0.3));
    view = {...view, ...targetView(), half: view.half};
    draw();
  });
  svg.addEventListener("pointerup", () => {
    if (drag && !drag.moved) {
      const g = drag.target.closest && drag.target.closest("[data-m]");
      if (g) select(g.dataset.m === selected ? null : g.dataset.m);
      else if (selected) select(null);
    }
    drag = null;
    svg.classList.remove("dragging");
  });
  $("reset").onclick = () => { selected = null; seeThrough = false; render(); animateTo({...HOME}); };
  const roofSel = $("roof");
  for (const [k, v] of Object.entries(ROOF_TYPES)) {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = v.name;
    roofSel.appendChild(o);
  }
  roofSel.onchange = () => {
    setRoof(roofSel.value);
    modelPoints();
    try { localStorage.setItem("shadeshift_atap", ROOF_TYPE); } catch (e) { /* storage blocked: not remembered */ }
    view = targetView();
    draw();
  };
  $("back").onclick = () => select(null);
  $("behind").onclick = () => { seeThrough = !seeThrough; render(); };
  window.addEventListener("resize", () => { draw(); postHeight(); });
  if (EMBEDDED && window.ResizeObserver) new ResizeObserver(() => postHeight()).observe(document.querySelector(".wrap"));

  // ---------- data ----------
  async function load() {
    if (!DEVICE) { $("status").textContent = "Pilih perangkat di dasbor."; return; }
    try {
      state = await api("/twin/state?device_id=" + encodeURIComponent(DEVICE));
      $("err").textContent = "";
    } catch (e) {
      $("err").textContent = "Tidak dapat membaca data: " + e.message;
    }
    if (!drag && !anim) render();
  }
  let atap = params.get("roof");
  if (!atap) { try { atap = localStorage.getItem("shadeshift_atap"); } catch (e) { atap = null; } }
  setRoof(atap || "pelana");
  roofSel.value = ROOF_TYPE;
  modelPoints();
  view = targetView();
  const focus = params.get("panel");
  if (focus && PANELS.includes(focus)) selected = focus;
  load().then(() => { if (selected) select(selected); });
  setInterval(() => { if (!drag && !anim) load(); }, 3000);
}
