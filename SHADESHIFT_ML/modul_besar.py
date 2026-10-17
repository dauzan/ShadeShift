"""Modul sintetis kelas ~450 W (72 sel setara, 3 dioda pelewat), diskalakan dari modul 10 W: arus sel x20,8."""
import numpy as np
from scipy.constants import k as kB, e as qe
import sim_core as sc

def modul_besar(s=20.8, Ns=72, ng=3):
    a = sc.PARAMS[0]  # modul A 10 W sebagai dasar
    return dict(I_L_ref=a["I_L_ref"] * s, I_o_ref=a["I_o_ref"] * s, R_s=a["R_s"] * (Ns / 36) / s,
                R_sh_ref=a["R_sh_ref"] * (Ns / 36) / s, a_ref=1.0 * Ns * kB * 298.15 / qe,
                alpha_sc=0.0006 * 0.6 * s, EgRef=1.121, dEgdT=-0.0002677, Ns=Ns, N_GROUP=ng)

def pasang():
    p = modul_besar(); sc.pasang_modul([dict(p) for _ in range(4)], isc=p["I_L_ref"], voc=47.0)
    return p
