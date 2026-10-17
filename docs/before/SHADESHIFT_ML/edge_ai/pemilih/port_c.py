"""Tiruan langkah demi langkah dari pemilih.h (float32, loop eksplisit) untuk memeriksa bahwa logika C sama dengan
pipeline Python asli (numpy interp, np.convolve 'same', scipy find_peaks dengan prominence, StandardScaler + LogisticRegression)."""
import numpy as np

f = np.float32
N = 201
FRAKSI = [f(0.1 * k) for k in range(1, 10)]


def interp(x, X, Y, n):
    """np.interp untuk X naik (boleh ada nilai kembar); di luar rentang dijepit ke ujung."""
    if x <= X[0]: return Y[0]
    if x >= X[n - 1]: return Y[n - 1]
    lo, hi = 0, n - 1                                   # cari j terbesar dengan X[j] <= x
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if X[mid] <= x: lo = mid
        else: hi = mid
    dx = X[hi] - X[lo]
    if dx <= 0: return Y[hi]
    return f(Y[lo] + (Y[hi] - Y[lo]) * ((x - X[lo]) / dx))


def cuplik_ulang(Vm, Im):
    """Buang V <= 0, jepit I >= 0, urutkan menurut V, rata-ratakan I pada V kembar, cuplik ulang ke 201 titik merata."""
    pts = [(f(v), f(max(i, 0.0))) for v, i in zip(Vm, Im) if v > 0]
    for a in range(1, len(pts)):                        # urut sisipan (stabil)
        k = pts[a]; b = a - 1
        while b >= 0 and pts[b][0] > k[0]: pts[b + 1] = pts[b]; b -= 1
        pts[b + 1] = k
    X, Y = [], []                                       # titik bertegangan sama: arus dirata-ratakan
    a = 0
    while a < len(pts):
        b = a; s = f(0)
        while b < len(pts) and pts[b][0] == pts[a][0]: s = f(s + pts[b][1]); b += 1
        X.append(pts[a][0]); Y.append(f(s / f(b - a))); a = b
    n = len(X)
    v0, v1 = X[0], X[n - 1]
    V = np.array([f(v0 + (v1 - v0) * f(k) / f(N - 1)) for k in range(N)], dtype=f)
    I = np.array([interp(v, X, Y, n) for v in V], dtype=f)
    return V, I


def puncak_menonjol(x, ambang):
    """scipy.signal.find_peaks(x, prominence=ambang): maksimum lokal (dataran diambil tengahnya) dengan prominence >= ambang."""
    n = len(x); hasil = []; i = 1
    while i < n - 1:
        if x[i - 1] < x[i]:
            ia = i + 1
            while ia < n - 1 and x[ia] == x[i]: ia += 1
            if x[ia] < x[i]:
                pk = (i + ia - 1) // 2
                # prominence: minimum ke kiri sampai nilai lebih tinggi / tepi, idem ke kanan
                kmin = x[pk]; j = pk
                while j >= 0 and x[j] <= x[pk]:
                    if x[j] < kmin: kmin = x[j]
                    j -= 1
                nmin = x[pk]; j = pk
                while j <= n - 1 and x[j] <= x[pk]:
                    if x[j] < nmin: nmin = x[j]
                    j += 1
                if x[pk] - max(kmin, nmin) >= ambang: hasil.append(pk)
                i = ia
        i += 1
    return hasil


def fitur_bentuk(V, I):
    P = np.array([f(V[k] * I[k]) for k in range(N)], dtype=f)
    k = int(np.argmax(P)); Pmax = P[k]; Voc = V[N - 1]; Isc = I[0]
    if Pmax <= 0 or Isc <= 0: return np.zeros(14, dtype=f)
    Ps = np.zeros(N, dtype=f)
    for a in range(N):
        s = f(0)
        for b in range(a - 2, a + 3):
            if 0 <= b < N: s = f(s + P[b])
        Ps[a] = f(s / f(5))
    pk = puncak_menonjol(Ps, f(f(0.02) * Pmax))
    h1 = h2 = f(0)
    for p in pk:
        v = Ps[p]
        if v > h1: h2 = h1; h1 = v
        elif v > h2: h2 = v
    p2 = f(h2 / h1) if len(pk) > 1 else f(0)
    ir = [f(interp(f(fr * Voc), V, I, N) / Isc) for fr in FRAKSI]
    return np.array([f(V[k] / Voc), f(I[k] / Isc), f(Pmax / f(Voc * Isc)), f(max(len(pk), 1)), p2, *ir], dtype=f)


def pilih(x, W):
    skor = []
    for c in range(3):
        s = W["bias"][c]
        for j in range(14): s = f(s + W["coef"][c][j] * f((x[j] - W["mean"][j]) / W["scale"][j]))
        skor.append(s)
    return int(np.argmax(skor)), skor
