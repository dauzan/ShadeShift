"""Jalur B langkah 3: CNN 1D kecil pada kurva mentah (4 susunan x 64 titik, I/Isc pada V/Voc merata), dilatih HANYA pada data
kembaran teracak, diuji pada data kembaran tahan dan kurva lab. Augmentasi saat latih: derau arus, pergeseran gain kecil.
Jalankan dengan Python ber-PyTorch dari folder SHADESHIFT_ML:
D:/software/venv_torch/Scripts/python.exe edge_ai/kembaran_lab/cnn_diagnosis.py"""
import os, sys, glob, re
import numpy as np, pandas as pd, torch, torch.nn as nn
sys.path.insert(0, os.getcwd())
torch.manual_seed(0); np.random.seed(0)
H = os.path.dirname(os.path.abspath(__file__)); TOPO4 = ["4S", "2S2P", "TCT", "4P"]
KELAS = ["normal", "bayangan opak", "tembus cahaya", "dioda terbuka", "dioda hubung singkat", "hambatan seri naik"]
LAB = {"V1": 0, "V1b": 0, "V1c": 0, "V3_opak": 1, "V3_paranet65": 2, "V3_paranet75": 2, "V4_paranet65": 2, "V4_paranet75": 2,
       "V6_paranet65": 2, "V6_paranet75": 2, "V5_paranet65": 3, "V5_paranet75": 3}


def baca(path):
    rows = []
    for ln in open(path, encoding="utf8"):
        p = ln.strip().split(",")
        if ln.startswith("#") or len(p) != 3 or p[0] == "V": continue
        try: rows.append([float(x) for x in p[:2]])
        except ValueError: pass
    d = pd.DataFrame(rows, columns=["V", "I"]); d["I"] = d.I.clip(lower=0)
    d = d[d.V > 0].groupby("V", as_index=False).I.mean()
    V = np.linspace(d.V.min(), d.V.max(), 201); I = np.interp(V, d.V, d.I)
    return np.interp(np.linspace(0, 1, 64) * V[-1], V, I) / I[0]


lab = {}
for f in glob.glob("data/data_lab/*.csv") + glob.glob("data/data_lab/_V5_anomali_dioda/*.csv"):
    m = re.match(r"(.+)_(4S|2S2P|TCT|4P)_u(\d)\.csv$", os.path.basename(f))
    if not m or m.group(1) not in LAB: continue
    lab.setdefault((m.group(1), int(m.group(3))), {})[m.group(2)] = baca(f)
lab = {k: v for k, v in lab.items() if len(v) == 4}
Xlab = np.stack([np.stack([v[t] for t in TOPO4]) for v in lab.values()]).astype(np.float32)
ylab = np.array([LAB[k[0]] for k in lab]); klab = [k[0] for k in lab]

d = pd.read_csv("data/kembaran/kembaran_acak.csv")
X = np.stack([d[[f"{t}~{j}" for j in range(64)]].values for t in TOPO4], axis=1).astype(np.float32); y = d.kelas.values
idx = np.random.permutation(len(d)); n = int(0.8 * len(d)); itr, ite = idx[:n], idx[n:]


class Jaringan(nn.Module):
    def __init__(s):
        super().__init__()
        s.f = nn.Sequential(nn.Conv1d(4, 16, 5, padding=2), nn.ReLU(), nn.Conv1d(16, 32, 5, stride=2, padding=2), nn.ReLU(),
                            nn.Conv1d(32, 32, 3, stride=2, padding=1), nn.ReLU(), nn.AdaptiveAvgPool1d(1))
        s.o = nn.Linear(32, 6)
    def forward(s, x): return s.o(s.f(x).squeeze(-1))


net = Jaringan(); print("parameter:", sum(p.numel() for p in net.parameters()))
opt = torch.optim.Adam(net.parameters(), 2e-3); lossf = nn.CrossEntropyLoss()
Xt, yt = torch.tensor(X[itr]), torch.tensor(y[itr])
for ep in range(60):
    net.train(); perm = torch.randperm(len(Xt))
    for b in range(0, len(Xt), 128):
        j = perm[b:b + 128]; xb = Xt[j]
        xb = xb * (1 + 0.03 * torch.randn(len(j), 1, 1)) + 0.01 * torch.randn_like(xb)    # augmentasi
        opt.zero_grad(); l = lossf(net(xb), yt[j]); l.backward(); opt.step()
    if ep % 10 == 9:
        net.eval()
        with torch.no_grad():
            acc = (net(torch.tensor(X[ite])).argmax(1).numpy() == y[ite]).mean() * 100
            pl = net(torch.tensor(Xlab)).argmax(1).numpy()
        utama = ylab < 3
        print("epoch %d: akurasi kembaran tahan %.1f%% | lab (normal/opak/paranet) %.1f%%" % (ep + 1, acc, (pl[utama] == ylab[utama]).mean() * 100))
net.eval()
with torch.no_grad(): pl = net(torch.tensor(Xlab)).argmax(1).numpy()
utama = ylab < 3
print(pd.crosstab(pd.Series([["normal", "opak", "paranet"][v] for v in ylab[utama]], name="label lab"), pd.Series([KELAS[v] for v in pl[utama]], name="tebakan")))
print("V5 (dioda bermasalah):", [KELAS[v] for v in pl[~utama]])
torch.save(net.state_dict(), os.path.join(H, "cnn_diagnosis.pt"))
