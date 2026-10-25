"""TEST-ONLY fake devices shared by several tests.

FakeV21 answers like firmware v2.1: the 4 topologies replay REAL lab curves; the single panels are SYNTHETIC (the lab 4P
curve with the current divided by 4); every sweep gets '# cahaya=' lines. GatewayV21 is a serial gateway wired to it.
"""
from shadeshift import inti, koneksi, protocol
from shadeshift.gateway.main import Gateway


class FakeV21(koneksi.ESPTiruan):
    """TEST ONLY: answers like firmware v2.1. Topologies replay lab curves; single panels are SYNTHETIC
    (the lab 4P curve with I / 4, times panel_scale[panel] to imitate a shaded panel); every sweep gets '# cahaya=' lines."""

    def __init__(self, condition, tmp_path, panel_scale=None):
        super().__init__(condition, lambat=0, seed=1)
        panel_scale = panel_scale or {}
        for ul in self.semua[condition].values():
            src = ul["4P"]
            for panel in protocol.PANELS:
                k = panel_scale.get(panel, 1.0)
                out = tmp_path / f"{panel}_x{k:g}_{src.split('/')[-1].split(chr(92))[-1]}"
                if not out.exists():
                    rows = []
                    for ln in open(src, encoding="utf8").read().splitlines():
                        parts = ln.split(",")
                        if ln.startswith("#"):
                            rows.append(ln.replace("topologi=4P", f"topologi={panel}"))
                        elif len(parts) == 3 and parts[0] != "V":
                            rows.append(f"{parts[0]},{float(parts[1]) / 4 * k:.6f},{float(parts[2]) / 4 * k:.6f}")
                        else:
                            rows.append(ln)
                    out.write_text("\n".join(rows) + "\n", encoding="utf8")
                ul[panel] = str(out)

    def _jalankan(self, baris):
        cmd = baris.split()[0].upper() if baris.strip() else ""
        if cmd == "INFO":
            return self._cetak("# INFO fw=2.1.0, id=a1b2c3d4e5f6, n=201, fitur=panel,cahaya")
        if cmd in protocol.PANELS:
            f = self._berkas(cmd)
            self.topo = cmd
            return self._cetak(f"# topologi {cmd}, Voc = {inti.baca_berkas(f).voc:.2f} V", f"# siap: {cmd}")
        if cmd == "SWEEP":
            blok, asli = [], self._cetak
            self._cetak = lambda *b: blok.extend(b)
            try:
                super()._jalankan(baris)
            finally:
                self._cetak = asli
            k = next(n for n, ln in enumerate(blok) if ln.startswith("# topologi="))
            blok.insert(k + 1, "# cahaya=1.200 V")
            k = next(n for n, ln in enumerate(blok) if ln.startswith("# SELESAI"))
            blok.insert(k, "# cahaya_akhir=1.198 V")
            return asli(*blok)
        return super()._jalankan(baris)


class GatewayV21(Gateway):
    def __init__(self, settings, fake):
        super().__init__(settings, source="serial", port="SIM", lambat=0)
        self.fake = fake

    def connect(self):
        self.kon = koneksi.Koneksi("TIRUAN", simpan=False, lambat=0)
        self.kon.ser = self.fake
        self.firmware = "v2"
        self.kon.pengamat_baris.append(self._on_line)
        self.kon.pengamat_sapuan.append(self._on_sweep)
        self.kon.pengamat_pilih.append(self._on_selection)
        self.kon.kirim("INFO")


INFO = "# INFO fw=3.2.0, id=a1b2c3d4e5f6, n=201, w={w}, fitur=panel,cahaya,pemilih,web{diag}"


class Fake32(FakeV21):
    """TEST ONLY: firmware 3.2 with (or without) diagnosis_model.h. A 4S sweep carries a fixed '# pemilih=' line and DIAG
    answers with a fixed class, like the board's serial output; it does not compute anything."""

    def __init__(self, condition, tmp_path, weights, with_model=True):
        super().__init__(condition, tmp_path)
        self.weights, self.with_model = weights, with_model

    def _jalankan(self, baris):
        cmd = baris.split()[0].upper() if baris.strip() else ""
        if cmd == "INFO":
            return self._cetak(INFO.format(w=self.weights, diag=",diag" if self.with_model else ""))
        if cmd == "SCAN":                                   # ADS1115 and MCP4725 on the I2C bus
            return self._cetak("# scan I2C:", "#   ditemukan 0x48", "#   ditemukan 0x60")
        if cmd == "DIAG":
            self.topo = None
            if not self.with_model:
                return self._cetak("# DIAG GAGAL: belum ada model diagnosis (diagnosis_model.h). Latih dan aktifkan di "
                                   "halaman Model AI, lalu unggah ulang firmware v3.")
            return self._cetak("# diagnosis=partial_shading, yakin=0.840, model=diag-tree-uji, t_us=3200",
                               "# semua relai terbuka, MOSFET mati")
        if cmd == "SWEEP" and self.topo == "4S":            # firmware 3.x: the selector runs on the board after a 4S sweep
            blok, asli = [], self._cetak
            self._cetak = lambda *b: blok.extend(b)
            try:
                super()._jalankan(baris)
            finally:
                self._cetak = asli
            k = next(n for n, ln in enumerate(blok) if ln.startswith("# SELESAI"))
            blok.insert(k, "# pemilih=4S, skor=1.2;0.3;0.1, t_us=850")
            return asli(*blok)
        return super()._jalankan(baris)


class Gateway32(GatewayV21):
    def connect(self):
        super().connect()
        self.kon.kirim("SCAN")                         # as Gateway.connect does for a serial board
        self.firmware = "v3.2"
