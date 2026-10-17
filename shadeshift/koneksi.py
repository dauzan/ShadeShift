"""Koneksi ke ESP32 (serial 115200) atau ke ESP32 tiruan yang memutar ulang data lab. Inti gateway tepi (edge).
Utas pembaca mengumpulkan log, mengurai setiap sapuan (# MULAI ... # SELESAI, format sama dengan logger_shadeshift.py),
mengukur waktu pindah susunan dan waktu sapuan, dan memberi tahu pengamat (gateway) tiap baris dan tiap sapuan.
Perintah dikirim apa adanya; perpindahan susunan tetap lewat urutan aman firmware."""
import os, re, time, random, threading, collections, queue
from shadeshift import inti

T_PINDAH_S, T_SAPU_S = 0.65, 3.0                 # perkiraan dari tunda firmware (pindah ~0,61 s; sapuan ~3-4 s), belum diukur


class Dibatalkan(Exception):
    """Tugas dihentikan oleh stop/OFF; tidak ada perintah tugas yang dikirim lagi sesudahnya."""


class ESPTiruan:
    """Meniru keluaran firmware v2 untuk perintah 4S/2S2P/TCT/4P, SWEEP, OFF, VOC, STATUS, memakai kurva lab.
    Kondisi bayangan bisa diganti saat berjalan (meniru bayangan yang berubah). Dipakai untuk latihan dan cadangan demo.
    Perintah dijalankan satu per satu seperti firmware asli. Satu ulangan lab dipakai untuk semua susunan sampai kondisi
    berganti (seperti satu set pengukuran). Tiap sapuan memuat baris '# tiruan berkas=<berkas lab>' supaya data putar
    ulang tidak pernah tampak sebagai pengukuran."""

    def __init__(self, kondisi="V1c", lambat=1.0, seed=None):
        self.semua = inti.daftar_kondisi()
        self.acak = random.Random(seed)
        self.ulangan = None
        self.kondisi = kondisi
        self.lambat = lambat                     # pengali waktu tunda (0 untuk uji cepat)
        self.topo = None
        self.keluar = collections.deque()
        self.kunci = threading.Lock()
        self.siap = threading.Event()
        self._antre = queue.Queue()
        threading.Thread(target=self._pekerja, daemon=True).start()

    @property
    def kondisi(self):
        return self._kondisi

    @kondisi.setter
    def kondisi(self, nilai):
        if nilai != getattr(self, "_kondisi", None):
            self.ulangan = None                  # kondisi baru: pilih satu ulangan lab lagi
        self._kondisi = nilai

    def _cetak(self, *baris):
        with self.kunci: self.keluar.extend(baris)
        self.siap.set()

    def _berkas(self, t):
        ul = self.semua.get(self.kondisi, {})
        if self.ulangan not in ul or t not in ul[self.ulangan]:
            pilihan = sorted(u for u in ul if t in ul[u])
            if not pilihan: return None
            self.ulangan = self.acak.choice(pilihan)
        return ul[self.ulangan][t]

    def write(self, data):
        self._antre.put(data.decode().strip())

    def _pekerja(self):
        while True:
            baris = self._antre.get()
            if baris is None: return
            try: self._jalankan(baris)
            except Exception as e: self._cetak(f"# (tiruan) galat: {e}")

    def _jalankan(self, baris):
        cmd, _, arg = baris.partition(" "); cmd = cmd.upper()
        if cmd in inti.TOPO:
            time.sleep(T_PINDAH_S * self.lambat)                              # perkiraan waktu pindah relai
            f = self._berkas(cmd)
            if f is None:
                self.topo = None; self._cetak(f"# GAGAL: tiruan tidak punya data {self.kondisi} {cmd}", "# semua relai terbuka, MOSFET mati"); return
            self.topo = cmd
            self._cetak(f"# topologi {cmd}, Voc = {inti.baca_berkas(f).voc:.2f} V", f"# siap: {cmd}")
        elif cmd in ("OFF", "STOP"):
            self.topo = None; self._cetak("# semua relai terbuka, MOSFET mati")
        elif cmd == "SWEEP":
            if self.topo is None: self._cetak("# GAGAL: pilih topologi dulu (4S/2S2P/TCT/4P)"); return
            time.sleep(T_SAPU_S * self.lambat)                                # sapuan nyata belum diukur
            f = self._berkas(self.topo)
            isi = [ln.rstrip("\r\n") for ln in open(f, encoding="utf8")]
            label = arg or "tanpa_label"
            isi = [f"# MULAI {label}" if ln.startswith("# MULAI") else ln for ln in isi]
            isi.insert(1, f"# tiruan berkas={os.path.basename(f)}")
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

    def close(self): self._antre.put(None)


class Koneksi:
    def __init__(self, port, simpan=True, tiruan_kondisi="V1c", lambat=1.0, baud=115200, seed=None):
        self.port = port
        self.tiruan = port == "TIRUAN"
        if self.tiruan:
            self.ser = ESPTiruan(tiruan_kondisi, lambat, seed); simpan = False
        else:
            import serial
            self.ser = serial.Serial(port, baud, timeout=0.2); time.sleep(2)   # ESP32 reset saat port dibuka
        self.simpan = simpan
        self.log = collections.deque(maxlen=400)
        self.sapuan = []                            # semua Sapuan sesi ini, terbaru di akhir
        self.topo = None
        self.galat = None
        self.kerja = None                           # nama tugas otomatis yang sedang berjalan
        self.riwayat_pilih = []                     # hasil pilih otomatis
        self.pengamat_baris = []                    # fungsi(waktu, arah 'rx'/'tx', baris)
        self.pengamat_sapuan = []                   # fungsi(Sapuan, baris_blok)
        self.pengamat_pilih = []                    # fungsi(hasil, sapuan_4S, sapuan_pilihan)
        self._dikirim = {}                          # waktu kirim perintah terakhir: 'TOPO:4S', 'SWEEP'
        self.terakhir_dikirim = {}                  # waktu kirim terakhir per kata perintah (tidak dihapus)
        self._pindah_ms = None                      # waktu pindah susunan terakhir (dipasang ke sapuan berikutnya)
        self.henti = threading.Event()              # kait stop: sesudah stop/OFF, tugas tidak boleh menulis lagi
        self._tulis = threading.Lock()              # satu penulis serial pada satu waktu (stop vs tugas)
        self._ev = threading.Lock()
        self._pendengar = []
        self.hidup = True
        threading.Thread(target=self._baca, daemon=True).start()
        self.kirim("STATUS")                        # samakan keadaan relai dengan alat (ANALYSIS B10)

    # ---------- dasar ----------
    def _baca(self):
        buf = None
        while self.hidup:
            try: s = self.ser.readline().decode("utf8", errors="replace").rstrip()
            except Exception as e:
                self.galat = f"koneksi terputus: {e}"; self.hidup = False; break
            if not s: continue
            t = time.time()
            with self._ev:
                self.log.append((t, s))
                m = re.match(r"# siap: (\S+)", s)
                if m:
                    self.topo = m.group(1)
                    t0 = self._dikirim.pop(f"TOPO:{self.topo}", None)
                    self._pindah_ms = (t - t0) * 1000 if t0 else None
                m = re.match(r"# topologi=(\S+?), R0=(\w+)", s)                 # balasan STATUS
                if m: self.topo = m.group(1) if m.group(1) != "-" and m.group(2) == "tutup" else None
                if s.startswith("# semua relai terbuka") or "GAGAL: Voc" in s: self.topo = None
                if s.startswith("# MULAI"): buf = [s]
                elif buf is not None:
                    buf.append(s)
                    if s.startswith("# SELESAI"):
                        sp = inti.urai_baris(buf, sumber=self.port); sp.waktu = t
                        t0 = self._dikirim.pop("SWEEP", None)
                        sp.meta.update(sweep_ms=(t - t0) * 1000 if t0 else None, switch_ms=self._pindah_ms,
                                       cancelled=self.henti.is_set())        # selesai sesudah stop: jangan dipakai memutuskan
                        self._pindah_ms = None
                        if self.simpan: sp.sumber = self._simpan(sp.label, buf)
                        self.sapuan.append(sp)
                        for f in self.pengamat_sapuan: self._panggil(f, sp, list(buf))
                        buf = None
                for f in self.pengamat_baris: self._panggil(f, t, "rx", s)
                for q in self._pendengar: q.put(s)                  # sesudah sapuan tersimpan, supaya sapu() melihatnya

    def _panggil(self, f, *args):
        try: f(*args)
        except Exception as e: self.galat = f"pengamat: {e}"

    def _simpan(self, nama, baris):
        os.makedirs(inti.DATA_DASBOR, exist_ok=True)
        nama = re.sub(r"[^A-Za-z0-9_\-]", "_", nama) or "tanpa_label"
        path = os.path.join(inti.DATA_DASBOR, f"{nama}.csv"); n = 2
        while os.path.exists(path):
            path = os.path.join(inti.DATA_DASBOR, f"{nama}_{n}.csv"); n += 1
        with open(path, "w", encoding="utf8") as f: f.write("\n".join(baris) + "\n")
        return path

    def kirim(self, cmd):
        """Kirim satu baris ke alat. OFF/STOP selalu lewat hentikan(): satu jalur stop (ANALYSIS, review CON-1)."""
        cmd = cmd.strip()
        if not cmd: return
        if cmd.split()[0].upper() in ("OFF", "STOP"):
            self.hentikan(batas=0); return
        with self._tulis: self._tulis_baris(cmd)

    def _tulis_baris(self, cmd):
        t = time.time()
        kata = cmd.split()[0].upper()
        with self._ev:
            self.log.append((t, f">>> {cmd}"))
            self.terakhir_dikirim[kata] = t
            if kata in inti.TOPO: self._dikirim[f"TOPO:{kata}"] = t
            elif kata == "SWEEP": self._dikirim["SWEEP"] = t
        for f in self.pengamat_baris: self._panggil(f, t, "tx", cmd)
        self.ser.write((cmd + "\n").encode())

    def kirim_tugas(self, cmd):
        """Penulisan dari dalam tugas (pilih otomatis, mode otomatis, siklus, audit): ditolak sesudah stop."""
        with self._tulis:
            if self.henti.is_set(): raise Dibatalkan(cmd)
            self._tulis_baris(cmd)

    def hentikan(self, batas=10.0):
        """Stop: pasang kait (tugas berhenti menulis), kirim OFF, tunggu '# semua relai terbuka' sampai batas detik.
        Firmware menyelesaikan langkah yang sedang berjalan (sapuan bisa ~3-4 s) sebelum menjalankan OFF.
        Mengembalikan True bila alat mengonfirmasi (atau batas=0: tidak menunggu)."""
        q = queue.Queue()
        with self._ev: self._pendengar.append(q)
        try:
            with self._tulis:
                self.henti.set()
                self._tulis_baris("OFF")
            if batas <= 0: return True
            akhir = time.time() + batas
            while time.time() < akhir and self.hidup:
                try: s = q.get(timeout=0.2)
                except queue.Empty: continue
                if s.startswith("# semua relai terbuka"): return True
            return False
        finally:
            with self._ev: self._pendengar.remove(q)

    def lanjutkan(self):
        """Lepas kait stop: dipanggil saat pengguna memulai tugas atau perintah baru."""
        self.henti.clear()

    def tutup(self):
        self.hidup = False
        try: self.ser.close()
        except Exception: pass

    def _tunggu(self, cocok, batas, kirim=None):
        """Kirim perintah tugas (opsional), lalu tunggu baris baru yang memenuhi cocok(s); kembalikan baris itu atau None.
        Raises Dibatalkan bila stop terjadi sebelum atau selama menunggu."""
        q = queue.Queue()
        with self._ev: self._pendengar.append(q)
        try:
            if kirim: self.kirim_tugas(kirim)
            akhir = time.time() + batas
            while time.time() < akhir and self.hidup:
                if self.henti.is_set(): raise Dibatalkan(kirim or "tunggu")
                try: s = q.get(timeout=0.2)
                except queue.Empty: continue
                if cocok(s): return s
            return None
        finally:
            with self._ev: self._pendengar.remove(q)

    def pindah(self, t, batas=10):
        """Pindah susunan lewat urutan aman firmware. Hanya '# siap: <t>' untuk susunan yang diminta yang diterima
        (balasan susunan lain diabaikan, ANALYSIS B11)."""
        s = self._tunggu(lambda s: s.startswith(f"# siap: {t}") or s.startswith("# GAGAL"), batas, kirim=t)
        return s is not None and s.startswith(f"# siap: {t}")

    def sapu(self, label, batas=60):
        """SWEEP dengan label; sapuan dianggap berhasil hanya bila blok yang selesai membawa label yang sama."""
        n = len(self.sapuan)
        s = self._tunggu(lambda s: s.startswith("# SELESAI") or s.startswith("# GAGAL"), batas, kirim=f"SWEEP {label}")
        if not (s and s.startswith("# SELESAI") and len(self.sapuan) > n): return None
        sp = self.sapuan[n]
        return sp if sp.label == label else None

    # ---------- alur pemilih ----------
    def pilih_sekali(self, W, label="auto", putuskan=None, pemicu="auto_once"):
        """4S -> SWEEP -> pemilih -> pindah ke pilihan -> SWEEP. Mengembalikan dict hasil.
        putuskan(sapuan_4S) -> dict dengan 'pilihan' (dan info lain) atau None; tanpa putuskan dipakai port_c dengan bobot W.
        Stop di tengah alur: tidak ada perintah lagi yang dikirim, hasil berisi galat 'dibatalkan (stop)'."""
        try:
            return self._pilih_sekali(W, label, putuskan, pemicu)
        except Dibatalkan:
            return self._selesai({"galat": "dibatalkan (stop)", "pemicu": pemicu}, None, None)

    def _pilih_sekali(self, W, label, putuskan, pemicu):
        stamp = time.strftime("%H%M%S")
        t0 = time.time()
        if not self.pindah("4S"): return self._selesai({"galat": "gagal pindah ke 4S", "pemicu": pemicu}, None, None)
        s4 = self.sapu(f"{label}_{stamp}_4S")
        if s4 is None: return self._selesai({"galat": "sapuan 4S gagal", "pemicu": pemicu}, None, None)
        if self.henti.is_set(): raise Dibatalkan("sesudah sapuan 4S")
        if putuskan is not None:
            info = putuskan(s4)
        else:
            k, skor, _ = inti.pilih_susunan(s4, W)
            info = {"pilihan": k, "skor": skor} if k else None
        if not info or not info.get("pilihan"):                          # ANALYSIS B5
            alasan = (info or {}).get("galat") or "sapuan 4S kurang dari 10 titik valid"
            return self._selesai({"galat": alasan, "pemicu": pemicu, "sapuan_4S": s4.label}, s4, None)
        k = info["pilihan"]
        hasil = {"waktu": time.strftime("%H:%M:%S"), **info, "pmax_4S": s4.pmax, "sapuan_4S": s4.label, "pemicu": pemicu}
        sk = None
        if k != "4S":
            if not self.pindah(k): hasil["galat"] = f"gagal pindah ke {k}"; return self._selesai(hasil, s4, None)
            sk = self.sapu(f"{label}_{stamp}_{k}")
            if sk is None: hasil["galat"] = f"sapuan {k} gagal"; return self._selesai(hasil, s4, None)
            hasil["pmax_pilihan"] = sk.pmax
        else:
            hasil["pmax_pilihan"] = s4.pmax
        hasil["durasi_s"] = time.time() - t0
        return self._selesai(hasil, s4, sk)

    def _selesai(self, hasil, s4, sk):
        for f in self.pengamat_pilih: self._panggil(f, hasil, s4, sk)
        return hasil

    def mulai_tugas(self, nama, fungsi):
        if self.kerja: return False
        def jalan():
            try: fungsi()
            except Dibatalkan: pass
            except Exception as e: self.galat = f"{nama}: {e}"
            finally: self.kerja = None
        self.lanjutkan()                            # tugas baru dimulai pengguna: lepas kait stop
        self.kerja = nama
        threading.Thread(target=jalan, daemon=True).start()
        return True

    def mode_otomatis(self, W, henti: threading.Event, jeda_s=10.0, ambang=0.20, tahan_min_s=30.0, putuskan=None):
        """Aturan dari UNTUK_DAUZAN.md: pilih susunan, lalu sapu ulang susunan aktif tiap jeda_s; jalankan pemilih lagi
        hanya bila Pmax berubah > ambang dari Pmax saat keputusan terakhir, dan pindah paling cepat setelah tahan_min_s
        (anti bolak-balik). Sapuan memutus daya beberapa detik (alat hanya bisa mengukur daya dengan menyapu)."""
        h = self.pilih_sekali(W, putuskan=putuskan); self.riwayat_pilih.append(h)
        acuan, t_pindah = h.get("pmax_pilihan"), time.time()
        while not henti.is_set() and not self.henti.is_set() and self.hidup and acuan:
            if henti.wait(jeda_s) or self.henti.is_set(): break
            try: s = self.sapu(f"pantau_{time.strftime('%H%M%S')}_{self.topo}")
            except Dibatalkan: break
            if s is None: continue
            ubah = abs(s.pmax - acuan) / max(acuan, 1e-9)
            if ubah > ambang and time.time() - t_pindah >= tahan_min_s:
                h = self.pilih_sekali(W, putuskan=putuskan, pemicu="auto_trigger"); h["pemicu_alasan"] = f"daya berubah {ubah * 100:.0f}%"
                self.riwayat_pilih.append(h)
                acuan, t_pindah = h.get("pmax_pilihan", acuan), time.time()
