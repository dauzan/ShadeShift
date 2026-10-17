"""Koneksi dasbor ke ESP32 (serial 115200) atau ke ESP32 tiruan yang memutar ulang data lab.
Utas pembaca mengumpulkan log, mengurai setiap sapuan (# MULAI ... # SELESAI, format sama dengan logger_shadeshift.py)
dan menyimpannya ke data/data_dasbor/. Perintah dikirim apa adanya; perpindahan susunan tetap lewat urutan aman firmware."""
import os, re, time, random, threading, collections
import inti


class ESPTiruan:
    """Meniru keluaran firmware v2 untuk perintah 4S/2S2P/TCT/4P, SWEEP, OFF, VOC, STATUS, memakai kurva lab.
    Kondisi bayangan bisa diganti saat berjalan (meniru bayangan yang berubah). Dipakai untuk latihan dan cadangan demo."""

    def __init__(self, kondisi="V1c", lambat=1.0):
        self.semua = inti.daftar_kondisi()
        self.kondisi = kondisi
        self.lambat = lambat                     # pengali waktu tunda (0 untuk uji cepat)
        self.topo = None
        self.keluar = collections.deque()
        self.kunci = threading.Lock()
        self.siap = threading.Event()

    def _cetak(self, *baris):
        with self.kunci: self.keluar.extend(baris)
        self.siap.set()

    def _berkas(self, t):
        ul = self.semua.get(self.kondisi, {})
        pilihan = [u for u in ul if t in ul[u]]
        return ul[random.choice(pilihan)][t] if pilihan else None

    def write(self, data):
        threading.Thread(target=self._jalankan, args=(data.decode().strip(),), daemon=True).start()

    def _jalankan(self, baris):
        cmd, _, arg = baris.partition(" "); cmd = cmd.upper()
        if cmd in inti.TOPO:
            time.sleep(0.6 * self.lambat)                                     # perkiraan waktu pindah relai
            f = self._berkas(cmd)
            if f is None:
                self.topo = None; self._cetak(f"# GAGAL: tiruan tidak punya data {self.kondisi} {cmd}", "# semua relai terbuka, MOSFET mati"); return
            self.topo = cmd
            self._cetak(f"# topologi {cmd}, Voc = {inti.baca_berkas(f).voc:.2f} V", f"# siap: {cmd}")
        elif cmd in ("OFF", "STOP"):
            self.topo = None; self._cetak("# semua relai terbuka, MOSFET mati")
        elif cmd == "SWEEP":
            if self.topo is None: self._cetak("# GAGAL: pilih topologi dulu (4S/2S2P/TCT/4P)"); return
            time.sleep(1.5 * self.lambat)                                     # sapuan nyata belum diukur
            isi = [ln.rstrip("\n") for ln in open(self._berkas(self.topo), encoding="utf8")]
            label = arg or "tanpa_label"
            isi = [f"# MULAI {label}" if ln.startswith("# MULAI") else ln for ln in isi]
            self._cetak(*isi)
        elif cmd == "VOC":
            v = inti.baca_berkas(self._berkas(self.topo)).voc if self.topo else 0.0
            self._cetak(f"# V_array = {v:.3f} V")
        elif cmd == "STATUS":
            self._cetak(f"# topologi={self.topo or '-'}, R0={'tutup' if self.topo else 'buka'}, cekVoc=ON (TIRUAN, kondisi {self.kondisi})")
        else:
            self._cetak(f"# (tiruan) perintah {cmd} diabaikan")

    def readline(self):
        if not self.siap.wait(0.2): return b""
        with self.kunci:
            if not self.keluar: self.siap.clear(); return b""
            s = self.keluar.popleft()
            if not self.keluar: self.siap.clear()
        return (s + "\n").encode()

    def close(self): pass


class Koneksi:
    def __init__(self, port, simpan=True, tiruan_kondisi="V1c", lambat=1.0):
        self.port = port
        self.tiruan = port == "TIRUAN"
        if self.tiruan:
            self.ser = ESPTiruan(tiruan_kondisi, lambat); simpan = False
        else:
            import serial
            self.ser = serial.Serial(port, 115200, timeout=0.2); time.sleep(2)
        self.simpan = simpan
        self.log = collections.deque(maxlen=400)
        self.sapuan = []                            # semua Sapuan sesi ini, terbaru di akhir
        self.topo = None
        self.galat = None
        self.kerja = None                           # nama tugas otomatis yang sedang berjalan
        self.riwayat_pilih = []                     # hasil pilih otomatis
        self._ev = threading.Lock()
        self._pendengar = []
        self.hidup = True
        threading.Thread(target=self._baca, daemon=True).start()

    # ---------- dasar ----------
    def _baca(self):
        buf = None
        while self.hidup:
            try: s = self.ser.readline().decode("utf8", errors="replace").rstrip()
            except Exception as e:
                self.galat = f"koneksi terputus: {e}"; self.hidup = False; break
            if not s: continue
            with self._ev:
                self.log.append((time.time(), s))
                m = re.match(r"# siap: (\S+)", s)
                if m: self.topo = m.group(1)
                if s.startswith("# semua relai terbuka") or "GAGAL: Voc" in s: self.topo = None
                if s.startswith("# MULAI"): buf = [s]
                elif buf is not None:
                    buf.append(s)
                    if s.startswith("# SELESAI"):
                        sp = inti.urai_baris(buf, sumber=self.port); sp.waktu = time.time()
                        if self.simpan: sp.sumber = self._simpan(sp.label, buf)
                        self.sapuan.append(sp); buf = None
                for q in self._pendengar: q.put(s)                  # sesudah sapuan tersimpan, supaya sapu() melihatnya

    def _simpan(self, nama, baris):
        os.makedirs(inti.DATA_DASBOR, exist_ok=True)
        nama = re.sub(r"[^A-Za-z0-9_\-]", "_", nama) or "tanpa_label"
        path = os.path.join(inti.DATA_DASBOR, f"{nama}.csv"); n = 2
        while os.path.exists(path):
            path = os.path.join(inti.DATA_DASBOR, f"{nama}_{n}.csv"); n += 1
        with open(path, "w", encoding="utf8") as f: f.write("\n".join(baris) + "\n")
        return path

    def kirim(self, cmd):
        cmd = cmd.strip()
        if not cmd: return
        with self._ev: self.log.append((time.time(), f">>> {cmd}"))
        self.ser.write((cmd + "\n").encode())

    def tutup(self):
        self.hidup = False
        try: self.ser.close()
        except Exception: pass

    def _tunggu(self, cocok, batas, kirim=None):
        """Kirim perintah (opsional), lalu tunggu baris baru yang memenuhi cocok(s); kembalikan baris itu atau None."""
        import queue
        q = queue.Queue()
        with self._ev: self._pendengar.append(q)
        try:
            if kirim: self.kirim(kirim)
            akhir = time.time() + batas
            while time.time() < akhir and self.hidup:
                try: s = q.get(timeout=0.2)
                except queue.Empty: continue
                if cocok(s): return s
            return None
        finally:
            with self._ev: self._pendengar.remove(q)

    def pindah(self, t, batas=10):
        s = self._tunggu(lambda s: s.startswith("# siap:") or s.startswith("# GAGAL"), batas, kirim=t)
        return s is not None and s.startswith(f"# siap: {t}")

    def sapu(self, label, batas=60):
        n = len(self.sapuan)
        s = self._tunggu(lambda s: s.startswith("# SELESAI") or s.startswith("# GAGAL"), batas, kirim=f"SWEEP {label}")
        return self.sapuan[n] if s and s.startswith("# SELESAI") and len(self.sapuan) > n else None

    # ---------- alur pemilih (dihitung di laptop, sama dengan pemilih.h) ----------
    def pilih_sekali(self, W, label="auto"):
        """4S -> SWEEP -> pemilih -> pindah ke pilihan -> SWEEP. Mengembalikan dict hasil."""
        stamp = time.strftime("%H%M%S")
        t0 = time.time()
        if not self.pindah("4S"): return {"galat": "gagal pindah ke 4S"}
        s4 = self.sapu(f"{label}_{stamp}_4S")
        if s4 is None: return {"galat": "sapuan 4S gagal"}
        k, skor, _ = inti.pilih_susunan(s4, W)
        hasil = {"waktu": time.strftime("%H:%M:%S"), "pilihan": k, "skor": skor, "pmax_4S": s4.pmax, "sapuan_4S": s4.label}
        if k != "4S":
            if not self.pindah(k): hasil["galat"] = f"gagal pindah ke {k}"; return hasil
            sk = self.sapu(f"{label}_{stamp}_{k}")
            if sk is None: hasil["galat"] = f"sapuan {k} gagal"; return hasil
            hasil["pmax_pilihan"] = sk.pmax
        else:
            hasil["pmax_pilihan"] = s4.pmax
        hasil["durasi_s"] = time.time() - t0
        return hasil

    def mulai_tugas(self, nama, fungsi):
        if self.kerja: return False
        def jalan():
            try: fungsi()
            except Exception as e: self.galat = f"{nama}: {e}"
            finally: self.kerja = None
        self.kerja = nama
        threading.Thread(target=jalan, daemon=True).start()
        return True

    def mode_otomatis(self, W, henti: threading.Event, jeda_s=10.0, ambang=0.20, tahan_min_s=30.0):
        """Uji di laptop dari aturan di UNTUK_DAUZAN.md: pilih susunan, lalu sapu ulang susunan aktif tiap jeda_s;
        jalankan pemilih lagi hanya bila Pmax berubah > ambang dari Pmax saat keputusan terakhir, dan pindah paling cepat
        setelah tahan_min_s (anti bolak-balik). Belum ada di firmware; sapuan memutus daya beberapa detik."""
        h = self.pilih_sekali(W); self.riwayat_pilih.append(h)
        acuan, t_pindah = h.get("pmax_pilihan"), time.time()
        while not henti.is_set() and self.hidup and acuan:
            if henti.wait(jeda_s): break
            s = self.sapu(f"pantau_{time.strftime('%H%M%S')}_{self.topo}")
            if s is None: continue
            ubah = abs(s.pmax - acuan) / max(acuan, 1e-9)
            if ubah > ambang and time.time() - t_pindah >= tahan_min_s:
                h = self.pilih_sekali(W); h["pemicu"] = f"daya berubah {ubah * 100:.0f}%"; self.riwayat_pilih.append(h)
                acuan, t_pindah = h.get("pmax_pilihan", acuan), time.time()
