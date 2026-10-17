"""Gateway core (shadeshift/koneksi.py) against the emulated ESP32: fixes for ANALYSIS B5, B6, B10, B11 and timing."""
import time

from shadeshift import inti, koneksi, protocol


def _wait(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_status_sync_on_connect_and_replay_marker():
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V1c", lambat=0)
    try:
        assert _wait(lambda: any("topologi=-" in s for _, s in k.log))          # STATUS sent and answered
        assert k.pindah("TCT")
        blocks = []
        k.pengamat_sapuan.append(lambda sp, lines: blocks.append(lines))
        sp = k.sapu("uji_TCT")
        assert sp is not None and sp.label == "uji_TCT"
        p = protocol.parse_block(blocks[0])
        assert p.replay_of and p.replay_of.startswith("V1c_TCT_u")                # emulated data names its lab file
        assert sp.meta["sweep_ms"] is not None and sp.meta["switch_ms"] is not None
    finally:
        k.tutup()


def test_emulator_runs_commands_one_at_a_time():
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V1c", lambat=0.05)
    try:
        k.kirim("4S")
        k.kirim("SWEEP rapid")              # sent before the switch finished: the real firmware would queue it too
        assert _wait(lambda: len(k.sapuan) == 1)
        assert k.sapuan[0].label == "rapid" and k.sapuan[0].topologi == "4S"
    finally:
        k.tutup()


def test_switch_waits_for_the_requested_topology_only():
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V1c", lambat=0)
    try:
        k.ser._cetak("# siap: 2S2P")         # a stray line for another topology must not satisfy pindah("TCT")
        assert k.pindah("TCT") and k.topo == "TCT"
    finally:
        k.tutup()


def test_selection_without_valid_points_reports_instead_of_crashing():
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V1c", lambat=0)
    try:
        h = k.pilih_sekali(inti.muat_bobot(), putuskan=lambda sp: None)
        assert "galat" in h and "10" in h["galat"] and k.topo == "4S"
        h = k.pilih_sekali(inti.muat_bobot(), putuskan=lambda sp: {"pilihan": None, "galat": "incomplete"})
        assert h["galat"] == "incomplete"
    finally:
        k.tutup()


def _tx_lines(k):
    return [s[4:] for _, s in k.log if s.startswith(">>> ")]


def test_stop_during_auto_select_sends_nothing_after_off():
    # Review CON-1: before the fix, the flow sent the selector's topology and SWEEP after OFF and ended energized.
    import threading
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V6_paranet65", lambat=0.3)       # sweep ~0.9 s, switch ~0.2 s
    try:
        hasil = {}
        t = threading.Thread(target=lambda: hasil.update(k.pilih_sekali(inti.muat_bobot())))
        t.start()
        assert _wait(lambda: any(x.startswith("SWEEP") for x in _tx_lines(k)))      # inside the 4S sweep
        assert k.hentikan(batas=10)                                                  # device confirmed all off
        t.join(timeout=15)
        tx = _tx_lines(k)
        assert tx[tx.index("OFF") + 1:] == []                                        # nothing written after OFF
        assert hasil["galat"] == "dibatalkan (stop)" and k.topo is None
        assert k.sapuan[-1].meta["cancelled"] is True                               # the sweep that finished is marked
    finally:
        k.tutup()


def test_raw_off_also_latches_and_new_task_releases():
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V1c", lambat=0)
    try:
        assert k.pindah("4S")
        k.kirim("off")                                 # the OFF button goes through the same stop path
        assert k.henti.is_set()
        assert k.mulai_tugas("uji", lambda: None) and not k.henti.is_set()
    finally:
        k.tutup()


def test_emulator_off_waits_for_the_running_sweep_like_the_firmware():
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V1c", lambat=0.2)
    try:
        assert k.pindah("TCT")
        k.kirim_tugas("SWEEP x")
        time.sleep(0.1)
        assert k.hentikan(batas=10)
        assert len(k.sapuan) == 1 and len(k.sapuan[0].V) > 100                     # block completed, then all off
        assert k.topo is None
    finally:
        k.tutup()
