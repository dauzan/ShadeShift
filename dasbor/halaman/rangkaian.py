"""Rekomendasi Rangkaian (docs/CONTRACT.md §29): model 3D keempat panel dan rangkaiannya dengan aliran listrik, sebelum
dan sesudah perubahan; di bawahnya analisis AI, perbandingan daya semua rangkaian, dan tombol. Rangkaian hanya diubah
setelah pengguna menyetujuinya. Halaman disajikan server lokal (/rangkaian) dan dimuat di sini tanpa batang gulir sendiri."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

dev = U.kepala("Rekomendasi Rangkaian")
if dev:
    U.bingkai("/rangkaian", dev["id"], tinggi_awal=1500)        # the page itself says Mode demo for the demo device
