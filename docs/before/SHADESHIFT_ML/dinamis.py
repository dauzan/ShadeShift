"""Bayangan bergerak (daun, tepi bayangan bergerak, campuran): energi selama 20 menit pada jendela W24 dengan biaya
sapuan dan peralihan. Daya tiap topologi per detik dihitung dari simulasi; kebijakan dievaluasi sesudahnya."""
import numpy as np, pandas as pd, time
from sim_core import simulasi, TOPO
T_SAPU, T_SAKLAR = 3.0, 0.6        # detik; perkiraan dari firmware (sapuan 201 titik + urutan pemutusan)
DT, N = 1.0, 1200                  # 1 detik, 20 menit
K = ["4S", "2S2P", "TCT"]

def ar1(rng, tau, n):
    phi = np.exp(-DT / tau); x = np.zeros(n); x[0] = rng.standard_normal()
    for i in range(1, n): x[i] = phi * x[i - 1] + np.sqrt(1 - phi ** 2) * rng.standard_normal()
    return x

def skenario(jenis, rng):
    S = np.zeros((N, 4)); mode = ["opak"] * 4; nc = [1] * 4
    if jenis in ("daun", "campuran"):
        m = rng.choice(4, rng.integers(1, 3), replace=False)
        for i in m:
            mode[i] = "paranet"; lvl = rng.uniform(30, 70); sg = rng.uniform(10, 25)
            S[:, i] = np.clip(lvl + sg * ar1(rng, rng.uniform(1, 4), N), 0, 95)
    if jenis in ("bergerak", "campuran"):
        urut = [i for i in rng.permutation(4) if mode[i] == "opak"][:rng.integers(1, 3)]
        for j, i in enumerate(urut):
            t0 = rng.uniform(0, N * 0.5); lama = rng.uniform(300, 700); nc[i] = int(rng.choice([3, 6, 12]))
            S[:, i] = np.clip((np.arange(N) - t0) / lama, 0, 1) * rng.uniform(70, 100)
    return S, mode, nc

def deret(S, mode, nc, rng):
    f = list(rng.uniform(0.97, 1.03, 4)); P = np.zeros((N, 3)); ml = np.zeros(N)
    for t in range(N):
        tp, pw, m = simulasi(list(S[t]), mode, nc, 800.0, 45.0, f)
        P[t] = [pw["W24"][k] for k in K]; ml[t] = m
    return P, ml

def kebijakan(P, ml, nama, tdec=None, vote=1):
    n = len(P); cur = 0 if nama != "tetap TCT" else 2; E = 0.0; sw = 0; t = 0; dead_until = -1; ns = 0
    if nama == "tetap 4S": return P[:, 0].sum(), 0, 0
    if nama == "tetap TCT": return P[:, 2].sum(), 0, 0
    if nama == "oracle tiap detik":
        best = P.argmax(1); sw = int((np.diff(best) != 0).sum())
        e = P[np.arange(n), best].sum() - sum(P[t, best[t]] * (T_SAKLAR / DT) for t in range(1, n) if best[t] != best[t - 1])
        return e, sw, 0
    if nama.startswith("pemicu"):
        # sapuan hanya bila daya topologi aktif (rata-rata 30 detik) menyimpang > tdec (fraksi) dari acuan; jarak minimal 60 detik
        t = 0; cur = 0; E = 0.0; sw = 0; ns = 0
        while t < n:
            ns += 1; t_end = min(t + int(np.ceil(T_SAPU)), n); baru = int(P[min(t, n - 1)].argmax())
            if baru != cur: sw += 1; t_end = min(t_end + int(np.ceil(T_SAKLAR)), n); cur = baru
            ref = P[t_end:t_end + 10, cur].mean() if t_end < n else 0.0; tr = n; ta = t_end
            for u in range(t_end + 10, n):
                if u - ta >= 60 or True:
                    ma = P[max(u - 29, t_end):u + 1, cur].mean()
                    if u - t_end >= 60 and ref > 0.05 and abs(ma - ref) / ref > tdec: tr = u; break
            E += P[t_end:tr, cur].sum(); t = tr
        return E, sw, ns
    # periodik: setiap tdec detik lakukan sapuan (daya 0 selama T_SAPU), pilih topologi terbaik (vote = jumlah foto/sapuan)
    t = 0; cur = 0
    while t < n:
        sapuan = T_SAPU * vote; t_end = min(t + int(np.ceil(sapuan)), n)
        ns += vote
        pil = []
        for v in range(vote):
            tt = min(t + int(v * T_SAPU), n - 1); pil.append(int(P[tt].argmax()))
        baru = max(set(pil), key=pil.count)
        if baru != cur: sw += 1; t_end = min(t_end + int(np.ceil(T_SAKLAR)), n); cur = baru
        t2 = min(t_end + int(tdec), n)
        E += P[t_end:t2, cur].sum(); t = t2
    return E, sw, ns

if __name__ == "__main__":
    CACHE = []; rng = np.random.default_rng(11); rows = []; t0 = time.time()
    for jenis in ["daun", "bergerak", "campuran"]:
        for r in range(12):
            S, mode, nc = skenario(jenis, rng); P, ml = deret(S, mode, nc, rng); Em = ml.sum(); CACHE.append((jenis, P, ml))
            for nama, tdec, vote in [("tetap 4S", None, 1), ("tetap TCT", None, 1), ("oracle tiap detik", None, 1),
                                     ("sapuan tiap 30 s", 30, 1), ("sapuan tiap 2 menit", 120, 1), ("sapuan tiap 10 menit", 600, 1),
                                     ("pemicu 10%", 0.10, 1), ("pemicu 20%", 0.20, 1), ("2 menit, 3 foto (suara terbanyak)", 120, 3), ("10 menit, 3 foto (suara terbanyak)", 600, 3)]:
                E, sw, ns = kebijakan(P, ml, nama, tdec, vote)
                rows.append(dict(jenis=jenis, ulang=r, kebijakan=nama, pct_mlpe=E / Em * 100, peralihan=sw, sapuan=ns,
                                 terbaik_pasca=P.sum(0).max() / Em * 100))
        print(jenis, "selesai", round(time.time() - t0), "s", flush=True)
    import pickle; pickle.dump(CACHE, open("data/dinamis_deret.pkl", "wb"))
    df = pd.DataFrame(rows); df.to_csv("hasil/dinamis_ringkasan.csv", index=False)
    pd.set_option("display.width", 200)
    print(df.groupby(["jenis", "kebijakan"]).agg(pct_mlpe=("pct_mlpe", "mean"), peralihan=("peralihan", "mean"), sapuan=("sapuan", "mean")).round(1))
