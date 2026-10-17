"""Inti dasbor SHADESHIFT: baca sapuan (CSV atau teks serial), pemilih susunan (tiruan pemilih.h), kembaran digital lampu lab.
Tidak ada model baru di sini: pemilih memakai bobot dari edge_ai/pemilih/pemilih_bobot.h lewat port_c.py (sudah diverifikasi
sama dengan C), kembaran memakai edge_ai/kembaran_lab/cocokkan_lampu.py dengan parameter_lampu.json."""
import os, re, sys, json
from dataclasses import dataclass, field
import numpy as np

from shadeshift import config as _config

_S = _config.load()                                              # SHADESHIFT_ML_DIR / SHADESHIFT_LAB_DIR (CONTRACT §9)
ML = str(_S.ml_dir)
DATA_LAB = str(_S.lab_dir)
DATA_DASBOR = os.path.join(ML, "data", "data_dasbor")           # sapuan baru dari dasbor (data_lab mentah tidak diubah)
PEMILIH = os.path.join(ML, "edge_ai", "pemilih")
KEMBARAN = os.path.join(ML, "edge_ai", "kembaran_lab")
for p in (ML, PEMILIH, KEMBARAN):
    if p not in sys.path: sys.path.insert(0, p)

TOPO = ["4S", "2S2P", "TCT", "4P"]
KELAS = ["4S", "2S2P", "TCT"]                                     # keluaran pemilih (4P di bawah jendela 24 V)


# ---------------- sapuan ----------------
@dataclass
class Sapuan:
    label: str
    topologi: str
    V: np.ndarray
    I: np.ndarray
    voc_header: float = float("nan")
    pemilih_esp: str | None = None                                # bila firmware kelak mencetak "# pemilih=TCT"
    sumber: str = ""
    waktu: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def P(self): return self.V * self.I

    def kurva_bersih(self, n=201):
        """Seperti uji_data_fisik.baca(): V kembar dirata-ratakan, cuplik ulang 201 titik merata. Pmax dihitung dari sini
        supaya rugi pemilih sama dengan angka laporan (0,82% vs 2,71% tetap 2S2P)."""
        if len(self.V) < 2: return self.V, self.I
        Vu, inv = np.unique(self.V, return_inverse=True)
        Iu = np.bincount(inv, weights=self.I) / np.bincount(inv)
        V = np.linspace(Vu[0], Vu[-1], n)
        return V, np.interp(V, Vu, Iu)

    @property
    def pmax(self):
        V, I = self.kurva_bersih()
        return float((V * I).max()) if len(V) else 0.0

    @property
    def vmp(self):
        V, I = self.kurva_bersih()
        return float(V[int(np.argmax(V * I))]) if len(V) else float("nan")

    @property
    def imp(self):
        V, I = self.kurva_bersih()
        return float(I[int(np.argmax(V * I))]) if len(V) else float("nan")

    @property
    def voc(self):
        return self.voc_header if np.isfinite(self.voc_header) else (float(self.V.max()) if len(self.V) else float("nan"))

    @property
    def isc(self):
        return float(self.I.max()) if len(self.I) else float("nan")


def topologi_dari_label(label):
    for t in sorted(TOPO, key=len, reverse=True):
        if re.search(rf"(^|_){t}(_|$)", label): return t
    return "?"


def urai_baris(baris, sumber="", label=None):
    """Baris keluaran firmware (atau isi berkas CSV logger) -> Sapuan. Aturan data sama dengan skrip lain:
    baris dengan jumlah kolom bukan 3 dibuang (contoh V3_paranet75_TCT_u2), V <= 0 dibuang, I dijepit >= 0."""
    topo, voc, pem, rows = None, float("nan"), None, []
    for ln in baris:
        s = ln.strip()
        if s.startswith("# MULAI"):
            label = label or s[len("# MULAI"):].strip()
        elif s.startswith("#"):
            m = re.search(r"topologi=([0-9A-Z]+)", s)
            if m: topo = m.group(1)
            m = re.search(r"Voc=([-0-9.]+)", s)
            if m and "topologi=" in s: voc = float(m.group(1))
            m = re.search(r"pemilih=([0-9A-Z]+)", s)
            if m: pem = m.group(1)
        else:
            p = s.split(",")
            if len(p) != 3 or p[0] == "V": continue
            try: rows.append((float(p[0]), float(p[1])))
            except ValueError: pass
    a = np.array(rows, float).reshape(-1, 2)
    a = a[a[:, 0] > 0]
    label = label or "tanpa_label"
    return Sapuan(label=label, topologi=topo or topologi_dari_label(label), V=a[:, 0], I=np.clip(a[:, 1], 0, None),
                  voc_header=voc, pemilih_esp=pem, sumber=sumber)


def baca_berkas(path):
    with open(path, encoding="utf8", errors="replace") as f:
        return urai_baris(f.readlines(), sumber=path, label=os.path.splitext(os.path.basename(path))[0])


def daftar_kondisi(folder=DATA_LAB):
    """{kondisi: {ulangan: {topologi: path}}} dari nama <kondisi>_<susunan>_u<n>.csv."""
    out = {}
    if not os.path.isdir(folder): return out
    for f in sorted(os.listdir(folder)):
        m = re.match(r"(.+)_(4S|2S2P|TCT|4P)_u(\d+)\.csv$", f)
        if m: out.setdefault(m.group(1), {}).setdefault(int(m.group(3)), {})[m.group(2)] = os.path.join(folder, f)
    return out


# ---------------- pemilih (Edge AI) ----------------
def _larik(teks, nama):
    m = re.search(nama + r"\[[^\]]*\](?:\[[^\]]*\])?\s*=\s*\{(.*?)\};", teks, re.S)
    return [float(x) for x in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", m.group(1))]


def muat_bobot(path=os.path.join(PEMILIH, "pemilih_bobot.h")):
    """Baca bobot langsung dari header C supaya dasbor selalu sama dengan yang diunggah ke ESP32."""
    t = open(path, encoding="utf8").read()
    f = np.float32
    coef = np.array(_larik(t, "PEMILIH_BOBOT"), dtype=f).reshape(3, 14)
    return {"mean": np.array(_larik(t, "PEMILIH_RERATA"), dtype=f), "scale": np.array(_larik(t, "PEMILIH_SKALA"), dtype=f),
            "coef": coef, "bias": np.array(_larik(t, "PEMILIH_BIAS"), dtype=f)}


NAMA_FITUR = ["Vmp/Voc", "Imp/Isc", "FF", "n_puncak", "P2/Pmax"] + [f"I@{k / 10:.1f}Voc" for k in range(1, 10)]


def pilih_susunan(s: Sapuan, W):
    """Satu sapuan 4S -> (susunan, skor, fitur). Langkah sama dengan pemilih.h: cuplik ulang, 14 fitur, regresi logistik."""
    import port_c
    if len(s.V) < 10: return None, None, None
    V, I = port_c.cuplik_ulang(s.V, s.I)
    x = port_c.fitur_bentuk(V, I)
    k, skor = port_c.pilih(x, W)
    return KELAS[k], [float(v) for v in skor], x


# ---------------- kembaran digital (daya harapan) ----------------
_PAR = None


def parameter_lampu():
    global _PAR
    if _PAR is None: _PAR = json.load(open(os.path.join(KEMBARAN, "parameter_lampu.json")))
    return _PAR


def _par(skala):
    p = parameter_lampu()
    return [p["G0"] * skala, p["h"], p["cx"], p["cy"], p["sigma"], p["T"], p["k_sh"]]


# Bayangan nominal yang sama dengan cocokkan_lampu.py (modul 0 = A, 1 = B, 2 = C, 3 = D). Transmisi paranet dihitung dari
# rasio Isc 4P di cocokkan_lampu.py; dasbor memakai satu nilai yang dihitung sekali (lihat transmisi_paranet()).
BAYANGAN = {
    "Tanpa bayangan": {},
    "Opak 1 sel modul A (V3_opak)": {0: ("opak", 17)},
    "Paranet modul A (V3)": {0: "paranet"},
    "Paranet modul A+B (V4)": {0: "paranet", 1: "paranet"},
    "Paranet modul A+D diagonal (V6)": {0: "paranet", 3: "paranet"},
}


def bayangan_kembaran(nama, tau):
    return {m: (("paranet", tau) if v == "paranet" else v) for m, v in BAYANGAN[nama].items()}


def simulasi_kembaran(skala=1.0, bayangan=None):
    import cocokkan_lampu as kl
    return kl.simulasikan(_par(skala), bayangan or {})


def transmisi_paranet():
    """Transmisi paranet seperti cocokkan_lampu.py: rasio Isc 4P V3_paranet65 / V1c dari data lab, dicari dengan bagi dua."""
    import cocokkan_lampu as kl
    def isc4p(tp): return float(tp["4P"].I_of_V(0.05))
    def isc_lab(k):
        return np.mean([baca_berkas(os.path.join(DATA_LAB, f"{k}_4P_u{u}.csv")).isc for u in (1, 2, 3)])
    try: r_lab = isc_lab("V3_paranet65") / isc_lab("V1c")
    except (FileNotFoundError, ValueError): return 0.7
    acuan = isc4p(simulasi_kembaran()); lo, hi = 0.02, 1.0
    for _ in range(20):
        mid = (lo + hi) / 2; r = isc4p(simulasi_kembaran(1.0, {0: ("paranet", mid)})) / acuan
        lo, hi = (mid, hi) if r < r_lab else (lo, mid)
    return (lo + hi) / 2


def daya_harapan(tp):
    """Pmax tiap susunan dari kurva kembaran (V >= 0)."""
    out = {}
    for t, c in tp.items():
        m = c.V >= 0; P = c.V[m] * c.I[m]
        out[t] = float(P.max()) if m.any() else 0.0
    return out


def kurva_kembaran(tp, t, voc_maks):
    V = np.linspace(0, voc_maks * 1.02, 250)
    return V, np.clip(tp[t].I_of_V(V), 0, None)


def kalibrasi_skala(s: Sapuan, bayangan=None):
    """Cari pengali cahaya agar Pmax kembaran = Pmax terukur pada sapuan acuan (pakai sapuan TANPA bayangan)."""
    lo, hi = 0.05, 4.0
    for _ in range(22):
        mid = (lo * hi) ** 0.5
        p = daya_harapan(simulasi_kembaran(mid, bayangan))[s.topologi]
        lo, hi = (mid, hi) if p < s.pmax else (lo, mid)
    return (lo * hi) ** 0.5
