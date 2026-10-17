"""Expected power from the lab-lamp digital twin (kembaran) for the server (CONTRACT.md §5.6).

The twin is a simulation fitted on lab condition V1c (~8 % power error on 7 lab conditions, LAPORAN_JALUR_B.md).
It needs pvlib. Without it the service reports itself unavailable and everything else keeps working.
"""
import threading

import numpy as np

from shadeshift import inti, protocol

SHADINGS = {
    "none": "Tanpa bayangan",
    "opak_A": "Opak 1 sel modul A (V3_opak)",
    "paranet_A": "Paranet modul A (V3)",
    "paranet_AB": "Paranet modul A+B (V4)",
    "paranet_AD": "Paranet modul A+D diagonal (V6)",
}
LABEL = "simulation: lab-lamp twin, ~8 % power error on 7 lab conditions"


class Twin:
    def __init__(self):
        self._lock = threading.Lock()
        self._tau = None
        self._sims = {}
        self.available, self.reason = self._probe()

    @staticmethod
    def _probe():
        try:
            import pvlib  # noqa: F401
            import cocokkan_lampu  # noqa: F401  (imports sim_core, which needs pvlib)
            return True, None
        except Exception as e:  # ImportError, or a broken research module
            return False, f"{type(e).__name__}: {e}"

    def warm_up(self):
        if self.available:
            self.expected(1.0, "none")

    def _shading(self, shading):
        if shading not in SHADINGS:
            raise ValueError(f"unknown shading {shading!r}; known: {', '.join(SHADINGS)}")
        if self._tau is None:
            self._tau = inti.transmisi_paranet()
        return inti.bayangan_kembaran(SHADINGS[shading], self._tau)

    def _simulate(self, scale, shading):
        key = (round(float(scale), 3), shading)
        with self._lock:
            if key not in self._sims:
                self._sims[key] = inti.simulasi_kembaran(key[0], self._shading(shading))
            return self._sims[key]

    def expected(self, scale, shading):
        """{topology: expected Pmax (W)} for the given light scale and assumed shading."""
        if not self.available:
            raise RuntimeError(self.reason)
        return {t: round(p, 6) for t, p in inti.daya_harapan(self._simulate(scale, shading)).items()}

    def curve(self, topology, voc_max, scale, shading, n=250):
        if not self.available:
            raise RuntimeError(self.reason)
        tp = self._simulate(scale, shading)
        V = np.linspace(0, voc_max * 1.02, n)
        I = np.clip(tp[topology].I_of_V(V), 0, None)
        return V, I

    def calibrate(self, v, i, topology, header_voc=None):
        """Light scale so that the twin's Pmax equals the measured Pmax of an UNSHADED sweep."""
        if not self.available:
            raise RuntimeError(self.reason)
        s = protocol.to_sapuan(v, i, topology=topology, header_voc=header_voc)
        with self._lock:
            return float(inti.kalibrasi_skala(s))
