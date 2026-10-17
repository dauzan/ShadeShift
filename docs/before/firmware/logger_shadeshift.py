"""
Logger SHADESHIFT: terhubung ke ESP32 lewat USB, meneruskan perintah yang diketik,
dan otomatis menyimpan setiap SWEEP ke file CSV di folder data_lab/.

Pemakaian:
    pip install pyserial
    python logger_shadeshift.py COM3        (Windows; cek nomor COM di Device Manager)
    python logger_shadeshift.py /dev/ttyUSB0 (Linux/Mac)

Lalu ketik perintah seperti di Serial Monitor, misalnya:
    4S
    SWEEP V3_opak_4S_u1
Ketik KELUAR untuk berhenti. Tutup Serial Monitor Arduino dulu (port tidak bisa dipakai dua program).
"""
import os, re, sys, threading, time
import serial

port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_lab")
os.makedirs(FOLDER, exist_ok=True)
ser = serial.Serial(port, 115200, timeout=0.2)
time.sleep(2)

def simpan(nama, baris):
    nama = re.sub(r"[^A-Za-z0-9_\-]", "_", nama) or "tanpa_label"
    path = os.path.join(FOLDER, f"{nama}.csv"); n = 2
    while os.path.exists(path):
        path = os.path.join(FOLDER, f"{nama}_{n}.csv"); n += 1
    with open(path, "w", encoding="utf8") as f:
        f.write("\n".join(baris) + "\n")
    print(f">>> tersimpan: {os.path.abspath(path)}")

def baca():
    buf, nama = None, None
    while True:
        try:
            s = ser.readline().decode("utf8", errors="replace").rstrip()
        except serial.SerialException:
            print(">>> koneksi terputus"); return
        if not s: continue
        print(s)
        if s.startswith("# MULAI"):
            nama, buf = s[len("# MULAI"):].strip(), [s]
        elif buf is not None:
            buf.append(s)
            if s.startswith("# SELESAI"):
                simpan(nama, buf); buf = None

threading.Thread(target=baca, daemon=True).start()
print(f">>> terhubung ke {port}. File sweep disimpan di {os.path.abspath(FOLDER)}")
while True:
    cmd = input()
    if cmd.strip().upper() == "KELUAR": break
    ser.write((cmd.strip() + "\n").encode())
ser.close()
