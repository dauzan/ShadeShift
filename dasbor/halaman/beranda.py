"""Beranda: tampilan pusat untuk konsumen (docs/CONTRACT.md §19, §28). Model 3D susunan panel dengan kondisi tiap panel,
perawatan yang akan datang, masalah dalam kata-kata dan saran, serta kendali pemantauan. Halaman model disajikan server
lokal (/twin) dan dimuat di sini; ia membaca kondisi sendiri setiap 3 detik.

Satu batang gulir saja, milik halaman utama: bingkai model tidak bergulir sendiri (umum.bingkai)."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

dev = U.kepala("Beranda")
if dev:
    U.bingkai("/twin", dev["id"])
