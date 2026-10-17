"""
Jalankan satu kondisi uji SHADESHIFT secara otomatis:
  1. ukur Voc tiap panel sendiri (A, B, C, D) lalu atur VPANEL
  2. jalankan SIKLUS <label> <ulangan>
  3. simpan tiap SWEEP sebagai CSV di data_lab/
Saat firmware meminta suhu (Ketik LANJUT), skrip menunggu file data_lab/lanjut.flag
(buat file kosong itu setelah suhu dicatat, skrip menghapusnya sendiri).

Pemakaian:  python -u siklus_otomatis.py COM6 V1 3
"""
import os, re, sys, time
import serial

port = sys.argv[1]
label = sys.argv[2]
ulang = sys.argv[3] if len(sys.argv) > 3 else "3"
FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_lab")
os.makedirs(FOLDER, exist_ok=True)
FLAG = os.path.join(FOLDER, "lanjut.flag")
if os.path.exists(FLAG): os.remove(FLAG)

ser = serial.Serial(port, 115200, timeout=0.3)
time.sleep(2)
ser.reset_input_buffer()


def kirim(cmd, tunggu=0.6):
    ser.write((cmd + "\n").encode())
    t0 = time.time(); out = []
    while time.time() - t0 < tunggu:
        s = ser.readline().decode("utf8", errors="replace").strip()
        if s: out.append(s)
    for s in out: print("   ", s)
    return out


def voc():
    ser.write(b"VOC\n")
    t0 = time.time()
    while time.time() - t0 < 5:
        s = ser.readline().decode("utf8", errors="replace").strip()
        m = re.search(r"V_array = (-?[\d.]+) V", s)
        if m: return float(m.group(1))
    return None


def simpan(nama, baris):
    nama = re.sub(r"[^A-Za-z0-9_\-]", "_", nama) or "tanpa_label"
    path = os.path.join(FOLDER, f"{nama}.csv"); n = 2
    while os.path.exists(path):
        path = os.path.join(FOLDER, f"{nama}_{n}.csv"); n += 1
    with open(path, "w", encoding="utf8") as f:
        f.write("\n".join(baris) + "\n")
    print(f">>> tersimpan: {os.path.abspath(path)}", flush=True)


print(">>> OFF dan ukur Voc tiap panel", flush=True)
kirim("OFF", 1.5)
PANEL = {"A": ["RELAI 7 1"], "B": ["RELAI 8 1", "RELAI 2 1"], "C": ["RELAI 3 1", "RELAI 9 1"], "D": ["RELAI 10 1"]}
hasil = {}
for nm, cmds in PANEL.items():
    for c in cmds: kirim(c, 0.4)
    time.sleep(1.2)
    hasil[nm] = voc()
    kirim("OFF", 1.2)
    print(f">>> panel {nm}: Voc = {hasil[nm]} V", flush=True)
nilai = [v for v in hasil.values() if v is not None]
longgar = len(sys.argv) > 4 and sys.argv[4] == "longgar"   # skenario bayangan berat: panel boleh < 5 V
if len(nilai) < 4 or (min(nilai) < 5 and not longgar):
    print(">>> BERHENTI: ada panel yang Voc-nya tidak masuk akal (<5 V atau tidak terbaca)", flush=True)
    sys.exit(1)
rata, maks = sum(nilai) / 4, max(nilai)
vpanel = max(5.0, round(0.5 * (rata + maks), 1))
print(f">>> rata-rata {rata:.2f} V, maks {maks:.2f} V, selisih maks/min = {maks/min(nilai):.2f} -> VPANEL {vpanel}", flush=True)
kirim(f"VPANEL {vpanel}", 0.6)

print(f">>> MULAI SIKLUS {label} x{ulang}", flush=True)
ser.write(f"SIKLUS {label} {ulang}\n".encode())
buf, nama = None, None
selesai = False
while not selesai:
    s = ser.readline().decode("utf8", errors="replace").strip()
    if not s:
        if os.path.exists(FLAG):
            os.remove(FLAG); ser.write(b"LANJUT\n"); print(">>> LANJUT dikirim", flush=True)
        continue
    print(s, flush=True)
    if s.startswith("# MULAI"):
        nama, buf = s[len("# MULAI"):].strip(), [s]
    elif buf is not None:
        buf.append(s)
        if s.startswith("# SELESAI"):
            simpan(nama, buf); buf = None
    if "SIKLUS SELESAI" in s or "dihentikan" in s or "dibatalkan" in s or "GAGAL" in s and buf is None and "Voc" in s:
        selesai = True
kirim("OFF", 1.5)
print(">>> selesai", flush=True)
ser.close()
