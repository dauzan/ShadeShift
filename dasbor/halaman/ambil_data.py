"""Halaman Ambil data: sesi pengukuran berlabel dan scan penuh (docs/CONTRACT.md §12,
SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md dengan koreksi tim). Label = keterangan operator; data mentah tidak diubah."""
import os, sys
from datetime import datetime

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402
from shadeshift import fieldwork  # noqa: E402

st.header("Ambil data berlabel")
if not U.server_hidup(): st.stop()

alat = [d for d in U.get("/devices") if d["kind"] != "virtual"]
if not alat:
    st.info("Belum ada alat. Jalankan `run.py live` (ESP32 di USB) atau `run.py demo` (untuk mencoba alurnya).")
    st.stop()
alat.sort(key=lambda d: (not d["online"], d["kind"] != "esp32", d["id"]))
ids = [d["id"] for d in alat]
if st.session_state.get("alat_data") not in ids: st.session_state.alat_data = ids[0]
pilih = st.selectbox("Alat", ids, key="alat_data",
                     format_func=lambda i: next(f"{d['id']}  ({'ESP32' if d['kind'] == 'esp32' else 'TIRUAN / demo'}, "
                                                f"{'online' if d['online'] else 'offline'})" for d in alat if d["id"] == i))
dev = next(d for d in alat if d["id"] == pilih)
demo = dev["kind"] == "emulator"
fitur = ((dev.get("gateway") or {}).get("esp32") or {}).get("features") or []
ada_panel = not demo and "panel" in fitur
if demo:
    st.warning("**TIRUAN**: alat ini memutar ulang kurva lab lama. Berkas diberi nama `TIRUAN…` dan ekspornya ditandai "
               "DATA TIRUAN. Pakai hanya untuk mencoba alur, bukan sebagai data lapangan.")
elif not dev["online"]:
    st.error("ESP32 offline: gateway tidak mengirim detak. Cek kabel USB dan jendela gateway.")
if not demo and not ada_panel:
    st.info("Firmware alat tidak melaporkan sapuan per panel: scan hanya 4 topologi. Unggah firmware 3.2 "
            "(`firmware/CARA_PAKAI.md`) untuk acuan MLPE dan peta modul.")
if not demo and "cahaya" not in fitur:
    st.caption("Tanpa sensor cahaya (LDR): pemeriksaan perubahan cahaya tidak bisa dilakukan.")

kat = U.get("/fieldwork/catalog")
KODE = {c["code"]: c for c in kat["conditions"]}
KELAS = kat["diagnosis"]
TEMPAT = kat["places"]


def label_kelas(k):
    return "(belum dipilih)" if k is None else KELAS.get(k, k)


def ikon(ok):
    return "✅" if ok is True else "⚠️" if ok is False else "❔"


buka = U.get("/sessions", device_id=pilih, open=True)

# ---------------- sesi ----------------
if not buka:
    st.subheader("Mulai sesi baru")
    with st.form("sesi_baru"):
        a, b = st.columns(2)
        tempat = a.selectbox("Tempat", list(TEMPAT), format_func=TEMPAT.get)
        langit = b.selectbox("Langit", ["cerah", "berawan", "mendung", "- (dalam ruangan)"])
        lokasi = a.text_input("Lokasi, arah dan sudut panel", placeholder="atap gedung X, menghadap utara, 15°")
        operator = b.text_input("Operator")
        catatan = st.text_area("Catatan sesi", placeholder="angin, jenis lampu, jam mulai, dll.")
        if st.form_submit_button("Mulai sesi", type="primary"):
            try:
                U.post("/sessions", {"device_id": pilih, "place": tempat, "sky": langit, "location": lokasi or None,
                                     "operator": operator or None, "note": catatan or None})
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
    sesi = None
else:
    sesi = U.get(f"/sessions/{buka[0]['id']}")
    mulai = fieldwork.local_date(sesi["started_at"])
    st.success(f"**Sesi {sesi['id']}** · {TEMPAT[sesi['place']]} · {sesi.get('sky') or ''} · mulai {mulai:%d %b %H:%M} · "
               f"{len(sesi['scans'])} scan · operator {sesi.get('operator') or '-'}")
    berjalan = [sc for sc in sesi["scans"] if sc["status"] in ("queued", "running")]

    # ---------------- scan baru ----------------
    if berjalan:
        st.info("Scan sedang berjalan. Tunggu selesai atau tekan STOP (relai dibuka; sapuan yang sedang berjalan "
                "diselesaikan dulu).")
    else:
        st.subheader("Scan penuh berikutnya")
        kode = st.selectbox("Kondisi (kode protokol)", list(KODE), format_func=lambda k: f"{k} · {KODE[k]['description']}")
        c = KODE[kode]
        if c["note"]: st.caption(f"Catatan: {c['note']}")
        if kode.startswith("E"):
            st.warning("Gangguan disuntikkan: tekan **STOP** dan tunggu \"semua relai terbuka\" sebelum memasang atau "
                       "melepas dioda, resistor, atau kabel pintas. 4S bisa sekitar 88 V DC.")
        if kode == "A1":
            st.caption("A1 = acuan: ambil di awal dan di akhir sesi, untuk memeriksa hanyut cahaya/suhu.")
        k1, k2, k3 = st.columns(3)
        modul = k1.multiselect("Modul terdampak", list(fieldwork.MODULES), default=list(c["modules"]), key=f"mod_{kode}",
                               help="A kiri atas, B kiri bawah, C kanan atas, D kanan bawah. Variasikan modul: data lab "
                                    "lama selalu menaungi modul A.")
        opsi = [None] + list(KELAS)
        kelas = k2.selectbox("Kelas diagnosis", opsi, index=opsi.index(c["diagnosis"]), format_func=label_kelas,
                             key=f"kelas_{kode}")
        dinamis = k3.checkbox("Dinamis (bayangan bergerak / awan)", value=c["dynamic"], key=f"din_{kode}")
        k1, k2, k3 = st.columns(3)
        putaran = k1.number_input("Jumlah ulangan (putaran)", 1, 60, 30 if c["dynamic"] else 3, key=f"put_{kode}")
        jeda = k2.number_input("Jeda antarputaran (s), untuk suhu dan pendinginan", 0.0, 600.0,
                               0.0 if c["dynamic"] else 30.0, 5.0, key=f"jeda_{kode}")
        panel = k3.checkbox("Sapu juga panel A-D satu per satu", value=ada_panel, disabled=not ada_panel,
                            help="Acuan MLPE (jumlah Pmax keempat panel) dan bahan peta modul. Butuh firmware 3.2.")
        catatan = st.text_input("Catatan scan", key=f"cat_{kode}", placeholder="jam, arah bayangan, nomor foto, dll.")
        mods = "".join(sorted(modul))
        awalan = fieldwork.DEMO_PREFIX if demo else fieldwork.PLACES[sesi["place"]][0]
        nama = fieldwork.condition_name(awalan, datetime.now().astimezone(), kode, mods)
        n_target = len(fieldwork.scan_targets(panel and ada_panel))
        st.caption(f"Berkas: `{nama}_<susunan>_u<n>.csv` · {putaran} × {n_target} sapuan · perkiraan "
                   f"{putaran * n_target * 5 / 60 + (putaran - 1) * jeda / 60:.1f} menit")
        if st.button("▶ Mulai scan penuh", type="primary"):
            try:
                r = U.post(f"/sessions/{sesi['id']}/scans", {"code": kode, "modules": mods, "diagnosis": kelas,
                                                             "dynamic": dinamis, "rounds": int(putaran),
                                                             "panels": bool(panel and ada_panel), "pause_s": float(jeda),
                                                             "note": catatan or None})
                for w in r.get("warnings", []): st.toast(w)
                st.rerun()
            except RuntimeError as e:
                st.error(f"Scan ditolak: {e}")

    U.tombol_stop("stop_data")

    # ---------------- kemajuan scan (diperbarui tiap 2 s) ----------------
    @st.fragment(run_every=2.0)
    def kemajuan(sid):
        try:
            s = U.get(f"/sessions/{sid}")
        except (U.ServerMati, RuntimeError) as e:
            st.error(f"Tidak bisa membaca sesi: {e}"); return
        jalan = [sc for sc in s["scans"] if sc["status"] in ("queued", "running")]
        if not jalan: return
        sc = jalan[-1]
        st.progress(min(sc["n_sweeps"] / max(sc["n_expected"], 1), 1.0),
                    text=f"{sc['condition']}: {sc['n_sweeps']} / {sc['n_expected']} sapuan ({sc['status']})")
        ev = [e for e in U.get("/events", device_id=s["device_id"], limit=5)
              if e["message"].startswith(f"full scan {sc['condition']}: round")]
        if ev and (datetime.now().astimezone() - fieldwork.local_date(ev[0]["created_at"])).total_seconds() < sc["pause_s"] + 3:
            st.info(f"⏸ {ev[0]['message']}. Catat suhu punggung panel A-D di bawah.")
    kemajuan(sesi["id"])

    # ---------------- daftar scan, mutu, suhu, koreksi label ----------------
    if sesi["scans"]:
        st.subheader("Scan sesi ini")
        if st.button("Segarkan"): st.rerun()
        rows = []
        for sc in reversed(sesi["scans"]):
            gagal = [q["check"] for q in sc["quality"] if q["ok"] is False]
            rows.append({"id": sc["id"], "kode": sc["code"], "kondisi": sc["condition"], "kelas": label_kelas(sc["diagnosis"]),
                         "modul": sc["modules"] or "-", "ulangan": f"u{sc['repeat_start']}..u{sc['repeat_start'] + sc['rounds'] - 1}",
                         "panel": "ya" if sc["with_panels"] else "tidak", "status": sc["status"],
                         "sapuan": f"{sc['n_sweeps']}/{sc['n_expected']}",
                         "mutu": "✅" if not gagal else "⚠️ " + ", ".join(gagal), "hasil": sc.get("result") or ""})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        d = sesi["a1_drift"]
        st.caption(f"{ikon(d['ok'])} Hanyut A1 (awal vs akhir sesi): {d['detail']}")

        for n, sc in enumerate(reversed(sesi["scans"])):
            with st.expander(f"Scan {sc['id']} · {sc['condition']} · {sc['status']}", expanded=n == 0):
                for q in sc["quality"]:
                    st.markdown(f"{ikon(q['ok'])} **{q['check']}**: {q['detail']}")
                if sc["sweeps"]:
                    tab = pd.DataFrame([{"susunan": w["topology"], "ulangan": f"u{w['repeat']}", "Pmax": w["pmax"]}
                                        for w in sc["sweeps"]])
                    piv = tab.pivot_table(index="susunan", columns="ulangan", values="Pmax", aggfunc="first")
                    piv = piv.reindex([t for t in fieldwork.scan_targets(True) if t in piv.index])
                    st.markdown("Pmax (W) per susunan / panel dan ulangan")
                    st.dataframe(piv.style.format("{:.4f}", na_rep="-"), width="stretch")
                ulangan = [str(r) for r in range(sc["repeat_start"], sc["repeat_start"] + sc["rounds"])]
                with st.form(f"label_{sc['id']}"):
                    st.markdown("Suhu punggung panel (°C, termometer tembak) dan koreksi label")
                    suhu = {}
                    for u in ulangan:
                        kol = st.columns(5)
                        kol[0].markdown(f"u{u}")
                        lama = sc["temps"].get(u, {})
                        suhu[u] = {m: kol[i + 1].number_input(m, -20.0, 120.0, value=lama.get(m), step=0.1,
                                                              key=f"t_{sc['id']}_{u}_{m}", label_visibility="visible")
                                   for i, m in enumerate(fieldwork.MODULES)}
                    a, b = st.columns(2)
                    kls = a.selectbox("Kelas diagnosis", [None] + list(KELAS), format_func=label_kelas,
                                      index=([None] + list(KELAS)).index(sc["diagnosis"]), key=f"k_{sc['id']}")
                    mdl = b.multiselect("Modul terdampak", list(fieldwork.MODULES), default=list(sc["modules"]),
                                        key=f"m_{sc['id']}")
                    cat = st.text_input("Catatan", value=sc.get("note") or "", key=f"c_{sc['id']}")
                    if st.form_submit_button("Simpan"):
                        body = {"temps": {u: {m: v for m, v in row.items() if v is not None} for u, row in suhu.items()},
                                "modules": "".join(sorted(mdl)), "note": cat}
                        if kls: body["diagnosis"] = kls
                        try:
                            U.put(f"/scans/{sc['id']}", body); st.toast("Tersimpan"); st.rerun()
                        except RuntimeError as e:
                            st.error(str(e))
                st.caption("Nama berkas tetap seperti saat scan dimulai; label yang dikoreksi tercatat di labels.csv.")
                if sc["sweeps"] and st.checkbox("Diagnosis AI dan peta modul", key=f"diag_{sc['id']}", value=n == 0):
                    dg = U.get(f"/scans/{sc['id']}/diagnosis")
                    for r in dg["rounds"][-1:]:
                        U.kartu_diagnosis(r, f"Putaran u{r['repeat']} (label operator: "
                                             f"{fieldwork.DIAGNOSIS.get(dg['label']['diagnosis'], '-')}, modul {dg['label']['modules'] or '-'})")

    a, b = st.columns(2)
    if a.button("Akhiri sesi", disabled=bool(berjalan)):
        try:
            U.post(f"/sessions/{sesi['id']}/end"); st.rerun()
        except RuntimeError as e:
            st.error(str(e))

# ---------------- ekspor ----------------
st.subheader("Ekspor sesi")
semua = U.get("/sessions", device_id=pilih)
if not semua:
    st.caption("Belum ada sesi.")
else:
    sid = st.selectbox("Sesi", [s["id"] for s in semua],
                       format_func=lambda i: next(f"sesi {s['id']} · {TEMPAT[s['place']]} · {s['started_at'][:16]} · "
                                                  f"{s['n_scans']} scan, {s['n_sweeps']} sapuan"
                                                  + (" · masih terbuka" if not s["ended_at"] else "")
                                                  for s in semua if s["id"] == i))
    if st.button("Siapkan zip"):
        try:
            st.session_state[f"zip_{sid}"] = U.unduh(f"/sessions/{sid}/export.zip")
        except (RuntimeError, U.ServerMati) as e:
            st.error(str(e))
    if st.session_state.get(f"zip_{sid}"):
        st.download_button("⬇ Unduh zip", st.session_state[f"zip_{sid}"], file_name=f"shadeshift_sesi{sid}.zip",
                           mime="application/zip")
    st.caption("Isi zip: `data/` berkas mentah persis seperti diterima dari alat, `_dibuang/` sapuan tidak lengkap, "
               "`labels.csv` (kondisi, kelas, modul, ulangan, cahaya, suhu, mutu), `sesi.json`, `BACA_SAYA.txt`. "
               "Pisahkan hari latih dan hari uji saat melatih model (protokol §5).")
