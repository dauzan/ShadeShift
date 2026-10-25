"""Optional Gemini rewording (CONTRACT §27): only reworded sentences that pass the guard are used; any failure keeps the
local sentences; the call happens in the background and never with device ids. No real network call in these tests."""
import json

import requests

from shadeshift import ai_teks

FAKTA = {"baru": {"judul": "Yang baru sejak pukul 10.05", "lines": ["2 pengukuran baru, dari pukul 10.10 sampai 10.15.",
                                                                    "Daya turun 31 persen dibanding pukul 10.05, dari 1,04 menjadi 0,72 watt."]},
         "day": {"headline": "Panel bekerja normal dalam 24 jam terakhir", "lines": ["Dalam 24 jam terakhir panel diukur 12 kali."]},
         "now": {"headline": "Semua panel dalam kondisi normal", "lines": ["Daya 0,72 watt, 70 persen dari perkiraan normal."]}}


class Jawab:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _gemini(teks):
    return Jawab(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(teks)}]}}]})


def _good():
    return {"baru": {"judul": "Ada 2 pengukuran baru sejak pukul 10.05", "lines": [
                "Pukul 10.10 sampai 10.15 ada 2 pengukuran baru.",
                "Daya turun 31 persen, dari 1,04 menjadi 0,72 watt."]},
            "day": {"headline": "Panel bekerja normal seharian", "lines": ["Panel diukur 12 kali dalam 24 jam terakhir."]},
            "now": {"headline": "Semua panel normal", "lines": ["Daya sekarang 0,72 watt, 70 persen dari perkiraan normal."]}}


def test_guard_keeps_numbers_and_words_only():
    assert ai_teks.periksa_jawaban(FAKTA, _good())["now"]["lines"][0].startswith("Daya sekarang 0,72 watt")
    for bad in ({**_good(), "now": {"headline": "Normal", "lines": ["Daya 0,75 watt."]}},          # a number not in the facts
                {**_good(), "now": {"headline": "Normal", "lines": ["Daya **0,72** watt."]}},      # markdown
                {**_good(), "now": {"headline": "Normal", "lines": ["Daya 70% dari normal."]}},    # a symbol
                {**_good(), "day": "ringkasan"}):                                                 # wrong shape
        try:
            ai_teks.periksa_jawaban(FAKTA, bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_rewording_used_only_when_it_passes():
    sent = []

    def post(url, json=None, timeout=None, headers=None):
        sent.append((url, json, headers))
        return _gemini(_good())
    p = ai_teks.Penulis("kunci-uji", "gemini-flash-latest", post=post)
    assert p.tulis(FAKTA, tunggu=True)["now"]["headline"] == "Semua panel normal"
    url, body, headers = sent[0]
    assert "gemini-flash-latest:generateContent" in url and headers["x-goog-api-key"] == "kunci-uji"
    assert "esp32" not in json.dumps(body) and "demo-01" not in json.dumps(body)                  # no device ids sent
    assert p.tulis(FAKTA) is not None and len(sent) == 1                                          # cached: no second call
    assert p.status["keadaan"] == "baik"


def test_failures_keep_the_local_sentences():
    def offline(*a, **k):
        raise requests.ConnectionError("no route")
    p = ai_teks.Penulis("kunci-uji", "x", post=offline)
    assert p.tulis(FAKTA, tunggu=True) is None and p.status["keadaan"] == "offline"
    assert p.tulis(FAKTA) is None                                                                 # waits before trying again
    for code, keadaan in ((404, "ditolak"), (429, "batas")):
        q = ai_teks.Penulis("k", "model-lama", post=lambda *a, **k: Jawab(code, {}))
        assert q.tulis(FAKTA, tunggu=True) is None and q.status["keadaan"] == keadaan
    liar = ai_teks.Penulis("k", "m", post=lambda *a, **k: _gemini({**_good(), "now": {"headline": "x", "lines": ["Daya 9 watt."]}}))
    assert liar.tulis(FAKTA, tunggu=True) is None and "angka" in liar.status["pesan"]
    assert ai_teks.Penulis("", "m").tulis(FAKTA) is None                                          # no key: never calls


def test_analysis_endpoint_without_a_key_and_no_gemini_row(tmp_path):
    from conftest import heartbeat, server_client
    with server_client(tmp_path) as api:
        heartbeat(api, "esp32-01")
        an = api.get("/api/v1/analisis", params={"device_id": "esp32-01"}).json()
        assert an["penulis"] == "lokal" and "Gemini" not in an["basis"]
        rows = {r["nama"]: r for g in api.get("/api/v1/devices/esp32-01/perangkat").json()["grup"] for r in g["baris"]}
        assert not any("Gemini" in n for n in rows)                    # not a part of the system on the Perangkat page
