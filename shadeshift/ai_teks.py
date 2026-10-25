"""Optional: Gemini (Google, free tier) rewords the analyser box in simpler words (docs/CONTRACT.md §27).

The light model on the laptop (kebiasaan, analisis_kurva) still produces every fact, number and verdict. Gemini only
rewrites those sentences for a home owner, and its answer is used only when it passes the guard: the same three boxes,
plain text, no number that is not in the facts. Anything else (no key, no internet, a refused key, an unknown model, the
free limit reached, a bad answer) keeps the local sentences, so the page never depends on the internet.

The call runs in a background thread when the facts change and its result is cached by the facts, so a page refresh
never waits for it: the first refresh after new data shows the local sentences, the next one the reworded ones. At most
one call every MIN_GAP_S seconds and MAX_PER_DAY a day (the free tier allows more); after a failure it waits
RETRY_AFTER_S. Only the analysis sentences are sent: no device id, no names. Free-tier content may be used by Google to
improve its products."""
import hashlib
import json
import logging
import re
import threading
import time

import requests

log = logging.getLogger("shadeshift.ai_teks")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT_S = 15
MIN_GAP_S = 20
RETRY_AFTER_S = 300
MAX_PER_DAY = 1000
CACHE_MAX = 64
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_SYMBOL = re.compile("[←-⯿\U0001f000-\U0001faff*#_`|<>%\\[\\]{}]")    # arrows, emoji, markdown, %: words only
BOXES = (("baru", "judul"), ("day", "headline"), ("now", "headline"))

PROMPT = """Anda menulis ulang ringkasan pemantauan panel surya untuk pemilik rumah yang bukan teknisi.
Tulis dalam bahasa Indonesia yang sederhana, ramah, dan singkat.
Aturan:
1. Pakai HANYA fakta di bawah. Jangan menambah fakta, angka, penyebab, atau saran yang tidak ada di fakta.
2. Setiap angka harus ditulis persis sama dengan angka di fakta (termasuk koma desimal). Jangan membulatkan atau menghitung.
3. Tanpa istilah teknis, tanpa emoji, tanpa simbol, tanpa tanda bintang atau format markdown.
4. Pertahankan kata "kemungkinan" bila fakta menyebut kemungkinan. Jangan membuat penyebab terdengar pasti.
5. Boleh menggabungkan kalimat yang berulang atau menghapus pengulangan; jangan menghapus angka atau saran.
6. Bagian yang kosong tetap kosong.
Jawab hanya JSON dengan bentuk yang sama persis dengan FAKTA:
{"baru": {"judul": "...", "lines": ["..."]}, "day": {"headline": "...", "lines": ["..."]}, "now": {"headline": "...", "lines": ["..."]}}

FAKTA:
"""


def _iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _numbers(text):
    return {n.replace(",", ".") for n in _NUM.findall(text)}


def periksa_jawaban(fakta, jawab):
    """The guard. Returns the reworded boxes, or raises ValueError with the reason."""
    if not isinstance(jawab, dict):
        raise ValueError("bukan JSON objek")
    boleh = _numbers(json.dumps(fakta, ensure_ascii=False))
    out = {}
    for box, head in BOXES:
        src, got = fakta.get(box), jawab.get(box)
        if src is None:
            continue
        if not isinstance(got, dict) or not isinstance(got.get(head), str) or not isinstance(got.get("lines"), list):
            raise ValueError(f"bentuk {box} salah")
        lines = [x.strip() for x in got["lines"] if isinstance(x, str) and x.strip()]
        if len(lines) > len(src["lines"]) + 1 or (src["lines"] and not lines):
            raise ValueError(f"jumlah kalimat {box} tidak wajar")
        for teks in [got[head], *lines]:
            if _SYMBOL.search(teks):
                raise ValueError("ada simbol atau format")
            asing = _numbers(teks) - boleh
            if asing:
                raise ValueError(f"angka yang tidak ada di fakta: {', '.join(sorted(asing))}")
        out[box] = {head: got[head].strip(), "lines": lines}
    return out


class Penulis:
    """Background rewording with a cache. tulis(fakta) returns the reworded boxes when they are ready, else None."""

    def __init__(self, key, model, post=None, clock=time.time):
        self.key, self.model = key or "", model or "gemini-flash-latest"
        self._post, self._clock = post or requests.post, clock
        self._cache, self._busy, self._lock = {}, set(), threading.Lock()
        self._last, self._fail_until, self._day, self._n = 0.0, 0.0, None, 0
        self.status = {"aktif": bool(self.key), "keadaan": "siap" if self.key else "mati", "pesan": None, "at": None,
                       "model": self.model}

    def tulis(self, fakta, tunggu=False):
        if not self.key:
            return None
        h = hashlib.sha256(json.dumps(fakta, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        with self._lock:
            if h in self._cache:
                return self._cache[h]
            now = self._clock()
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            if day != self._day:
                self._day, self._n = day, 0
            if h in self._busy or now < self._fail_until or now - self._last < MIN_GAP_S or self._n >= MAX_PER_DAY:
                return None
            self._busy.add(h)
            self._last, self._n = now, self._n + 1
        t = threading.Thread(target=self._panggil, args=(h, fakta), daemon=True)
        t.start()
        if tunggu:                                    # tests only
            t.join()
            return self._cache.get(h)
        return None

    def _gagal(self, keadaan, pesan):
        self._fail_until = self._clock() + RETRY_AFTER_S
        self.status = {**self.status, "keadaan": keadaan, "pesan": pesan, "at": _iso()}
        log.info("Gemini rewording off for %d s: %s", RETRY_AFTER_S, pesan)

    def _panggil(self, h, fakta):
        try:
            body = {"contents": [{"role": "user", "parts": [{"text": PROMPT + json.dumps(fakta, ensure_ascii=False)}]}],
                    "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json", "maxOutputTokens": 4096}}
            try:
                r = self._post(URL.format(model=self.model), json=body, timeout=TIMEOUT_S,
                               headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
            except requests.RequestException:
                return self._gagal("offline", "tidak ada sambungan internet")
            if r.status_code != 200:
                pesan = {400: "permintaan ditolak (kunci atau model salah)", 401: "kunci API ditolak",
                         403: "kunci API ditolak", 404: f"model {self.model} tidak ditemukan",
                         429: "batas gratis tercapai"}.get(r.status_code, f"jawaban server {r.status_code}")
                return self._gagal("ditolak" if r.status_code != 429 else "batas", pesan)
            try:
                teks = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                hasil = periksa_jawaban(fakta, json.loads(teks))
            except (KeyError, IndexError, TypeError, ValueError) as e:
                return self._gagal("jawaban", f"jawaban tidak dipakai: {e}")
            with self._lock:
                if len(self._cache) >= CACHE_MAX:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[h] = hasil
            self.status = {**self.status, "keadaan": "baik", "pesan": None, "at": _iso()}
        finally:
            with self._lock:
                self._busy.discard(h)
