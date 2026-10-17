"""Dipindah ke shadeshift/inti.py (dipakai bersama gateway, server, dan dasbor).
Shim ini menjaga `import inti` tetap jalan untuk app.py, uji_dasbor.py, dan skrip tim: modul yang dikembalikan
adalah shadeshift.inti itu sendiri."""
import importlib, os, sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path: sys.path.insert(0, _root)
sys.modules[__name__] = importlib.import_module("shadeshift.inti")
