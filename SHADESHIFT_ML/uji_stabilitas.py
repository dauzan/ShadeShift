"""Uji aturan stabilitas di simulasi bayangan bergerak (docs/CONTRACT.md §17). Kode riset dinamis.py tidak diubah:
skenario dan deret daya dibuat dengan fungsi dan benih yang sama (rng 11), jadi angka "tetap TCT" harus sama dengan
hasil/dinamis_ringkasan.csv (cek silang).

Kebijakan yang dibandingkan meniru mode otomatis gateway (shadeshift/koneksi.py), dengan biaya waktu yang sama:
- sapuan pantau tiap JEDA detik pada susunan aktif (daya 0 selama T_SAPU), pemilih dijalankan bila Pmax berubah > 20 %
  dari acuan dan sudah >= TAHAN detik sejak pindah terakhir (pilih_sekali: pindah ke 4S, sapu, putuskan, pindah, sapu);
- "+ stabil": sama, ditambah aturan stabilitas: bila simpangan baku / rata-rata Pmax 3 sapuan pantau terakhir (susunan
  yang sama; jendela = 3 x jeda) > CV, kunci TCT dan jangan menjalankan pemilih sampai stabil lagi.
Pemilih dianggap sempurna (memilih yang terbaik saat itu), sama dengan kebijakan di dinamis.py: yang diuji hanya aturannya.
Jalankan dari folder SHADESHIFT_ML: python uji_stabilitas.py   (sekitar 5 menit)
"""
import numpy as np, pandas as pd, time
from dinamis import K, N, T_SAPU, T_SAKLAR, deret, kebijakan, skenario

JEDA, TAHAN, AMBANG = 10, 30, 0.20       # sama dengan bawaan mode otomatis (settings.auto_mode_defaults)
CV = 0.10                                 # bawaan aturan stabilitas (belum divalidasi)
N_BACA = 3                                # jendela = 3 sapuan pantau terakhir (3 x jeda): dengan 30 s tetap, aturan
                                          # tidak pernah berlaku untuk jeda >= 15 s (temuan uji pertama, 20 Okt)
JEDA_UJI = (10, 60, 120, 300, 600)        # jeda sapuan pantau yang diuji (detik); bawaan dasbor 10 s
TCT = K.index("TCT")


def energi(P, stabil, JEDA=JEDA):
    JENDELA = N_BACA * JEDA
    """Energi mode otomatis (dengan / tanpa aturan stabilitas): susunan aktif dicatat per detik, daya dijumlahkan pada
    detik yang tidak sedang dipakai sapuan atau pindah. Mengembalikan (energi, jumlah pindah, jumlah kunci TCT)."""
    aktif = np.full(N, -1)
    mati = np.zeros(N, bool)

    def blok(a, d):
        mati[a:min(N, a + int(np.ceil(d)))] = True
        return a + int(np.ceil(d))

    def tandai(a, b, k):
        aktif[a:min(N, b)] = k

    t0 = 0
    t = blok(0, T_SAPU); baru = int(P[min(t, N - 1)].argmax())
    if baru != 0:
        t = blok(t, T_SAKLAR + T_SAPU)
    cur = baru; acuan, t_pindah, bacaan, terkunci, n_pindah, n_kunci = P[min(t, N - 1), cur], t, [], False, 0, 0
    tandai(t0, N, cur)
    while t < N:
        t += JEDA
        if t >= N:
            break
        t = blok(t, T_SAPU)
        p = P[min(t, N - 1), cur]
        bacaan = [(u, v) for u, v in bacaan if t - u <= JENDELA] + [(t, p)]
        vals = np.array([v for _, v in bacaan])
        if stabil and len(vals) >= 3 and vals.mean() > 0 and vals.std() / vals.mean() > CV:
            if not terkunci:
                n_kunci += 1
            terkunci = True
            if cur != TCT:
                t = blok(t, T_SAKLAR); cur = TCT; n_pindah += 1; bacaan = []; tandai(t, N, cur)
            acuan = p if cur == TCT else acuan
            continue
        if terkunci:
            terkunci = False
            acuan = p
        if acuan > 0 and abs(p - acuan) / acuan > AMBANG and t - t_pindah >= TAHAN:
            lama = cur
            t = blok(t, (T_SAKLAR if cur != 0 else 0) + T_SAPU)
            baru = int(P[min(t, N - 1)].argmax())
            if baru != 0:
                t = blok(t, T_SAKLAR + T_SAPU)
            cur = baru
            if cur != lama:
                n_pindah += 1; bacaan = []
            tandai(t, N, cur)
            acuan, t_pindah = P[min(t, N - 1), cur], t
    ok = (~mati) & (aktif >= 0)
    E = float(P[np.arange(N)[ok], aktif[ok]].sum())
    return E, n_pindah, n_kunci


if __name__ == "__main__":
    rng = np.random.default_rng(11); rows = []; t0 = time.time()
    for jenis in ["daun", "bergerak", "campuran"]:
        for r in range(12):
            S, mode, nc = skenario(jenis, rng); P, ml = deret(S, mode, nc, rng); Em = ml.sum()
            e_tct, _, _ = kebijakan(P, ml, "tetap TCT")
            e_or, _, _ = kebijakan(P, ml, "oracle tiap detik")
            hasil = [("tetap TCT", None, e_tct, 0, 0), ("ideal tiap detik", None, e_or, None, None)]
            for jeda in JEDA_UJI:                               # sapuan pantau memutus daya: seberapa sering masih untung?
                e_a, sw_a, _ = energi(P, False, jeda)
                e_s, sw_s, nk = energi(P, True, jeda)
                hasil += [("mode otomatis (pemicu 20 %)", jeda, e_a, sw_a, 0), ("mode otomatis + aturan stabilitas", jeda, e_s, sw_s, nk)]
            for nama, jeda, e, sw, kunci in hasil:
                rows.append(dict(jenis=jenis, ulang=r, kebijakan=nama, jeda_s=jeda, pct_mlpe=e / Em * 100, peralihan=sw, kunci_tct=kunci))
        print(jenis, "selesai", round(time.time() - t0), "s", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("hasil/stabilitas_ringkasan.csv", index=False)
    pd.set_option("display.width", 200)
    print(df.groupby(["jenis", "kebijakan", "jeda_s"], dropna=False).agg(pct_mlpe=("pct_mlpe", "mean"),
          peralihan=("peralihan", "mean"), kunci_tct=("kunci_tct", "mean")).round(2))
    w = df.assign(k=df.kebijakan + df.jeda_s.map(lambda x: "" if pd.isna(x) else f" @{int(x)}s")).pivot_table(
        index=["jenis", "ulang"], columns="k", values="pct_mlpe")
    for jeda in JEDA_UJI:
        a_, s_ = w[f"mode otomatis (pemicu 20 %) @{jeda}s"], w[f"mode otomatis + aturan stabilitas @{jeda}s"]
        print(f"jeda {jeda} s: aturan vs tanpa aturan " + ", ".join(
            f"{j} {g.mean():+.2f} (lebih baik {int((g > 0.05).sum())}, lebih buruk {int((g < -0.05).sum())})"
            for j, g in (s_ - a_).groupby(level=0)) + " | mode otomatis lebih buruk dari tetap TCT pada " + ", ".join(
            f"{j} {int((g < -0.05).sum())}/12" for j, g in (a_ - w["tetap TCT"]).groupby(level=0)))
