"""Dipindah ke shadeshift/koneksi.py (inti gateway: serial, ESP32 tiruan, alur pilih otomatis).
Shim ini menjaga `import koneksi` tetap jalan untuk app.py, uji_dasbor.py, dan skrip tim."""
import importlib, os, sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path: sys.path.insert(0, _root)
sys.modules[__name__] = importlib.import_module("shadeshift.koneksi")
