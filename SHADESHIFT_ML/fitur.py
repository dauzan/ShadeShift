import numpy as np
from scipy.signal import find_peaks
from sim_core import TOPO

FRAKSI = np.linspace(0.1, 0.9, 9)
NAMA_FITUR = ["Voc", "Isc", "Pmax", "Vmp_Voc", "Imp_Isc", "FF", "n_puncak", "P2_Pmax"] + [f"I@{f:.1f}Voc" for f in FRAKSI]

def sapuan(curve, rng=None, noise=True, N=201):
    """Meniru sapuan perangkat keras: N titik tegangan merata 0..Voc, derau ukur (I 1 persen, V 0,12 persen)."""
    voc = float(curve.V_of_I(0.0))   # V saat I = 0 (diperbaiki 8 Okt 2026: interp lama memakai I menurun -> Voc salah, sapuan melewati Voc)
    V = np.linspace(0.0, voc, N)
    I = curve.I_of_V(V)
    if noise and rng is not None:
        I = I * (1 + 0.01 * rng.standard_normal(N)); V = V * (1 + 0.0012 * rng.standard_normal(N))
    return V, I

def fitur(V, I):
    P = V * I; k = int(np.argmax(P)); Pmax = P[k]; Voc = V[-1]; Isc = I[0]
    if Pmax <= 0 or Isc <= 0: return np.zeros(len(NAMA_FITUR))
    Ps = np.convolve(P, np.ones(5) / 5, mode="same")
    pk, _ = find_peaks(Ps, prominence=0.02 * Pmax)
    h = np.sort(Ps[pk])[::-1] if len(pk) else np.array([Pmax])
    p2 = h[1] / h[0] if len(h) > 1 else 0.0
    ir = np.interp(FRAKSI * Voc, V, I) / Isc
    return np.array([Voc, Isc, Pmax, V[k] / Voc, I[k] / Isc, Pmax / (Voc * Isc), max(len(pk), 1), p2, *ir])
