"""The two model types the proposal names, in numpy/scipy only (no new dependency):

- LogReg: multinomial logistic regression on standardized features, L2 penalty, solved with L-BFGS. Same objective as
  scikit-learn's LogisticRegression(C=1.0) used by the research code: C * sum(log loss) + 0.5 * ||coef||^2 (bias free).
- Tree: a CART decision tree (Gini impurity), depth-limited, so it can be written as a few if/else lines for the ESP32.

Both predict class ids from a fixed list (only the classes seen in training can be predicted) and serialize to plain
JSON, so the registry stores them in SQLite and the C exporters can write them out.
"""
import numpy as np
from scipy.optimize import minimize


class LogReg:
    kind = "logreg"

    def __init__(self, C=1.0):
        self.C = float(C)

    def fit(self, X, y):
        X = np.asarray(X, float)
        y = np.asarray(y, int)
        self.classes = sorted(set(y.tolist()))
        k, n_f = len(self.classes), X.shape[1]
        self.mean = X.mean(0)
        self.scale = X.std(0)
        self.scale[self.scale == 0] = 1.0
        Z = (X - self.mean) / self.scale
        idx = np.searchsorted(self.classes, y)
        Y = np.eye(k)[idx]
        if k == 1:                                    # one class: constant prediction
            self.coef, self.bias = np.zeros((1, n_f)), np.zeros(1)
            return self

        def f(w):
            W, b = w[:k * n_f].reshape(k, n_f), w[k * n_f:]
            S = Z @ W.T + b
            S -= S.max(1, keepdims=True)
            logp = S - np.log(np.exp(S).sum(1, keepdims=True))
            loss = -self.C * (Y * logp).sum() + 0.5 * (W * W).sum()
            G = self.C * (np.exp(logp) - Y)
            return loss, np.concatenate([(G.T @ Z + W).ravel(), G.sum(0)])

        r = minimize(f, np.zeros(k * n_f + k), jac=True, method="L-BFGS-B", options={"maxiter": 5000, "gtol": 1e-6})
        self.coef, self.bias = r.x[:k * n_f].reshape(k, n_f), r.x[k * n_f:]
        return self

    def scores(self, X):
        return ((np.asarray(X, float) - self.mean) / self.scale) @ self.coef.T + self.bias

    def predict(self, X):
        return np.asarray(self.classes)[self.scores(X).argmax(1)]

    def proba(self, X):
        """{class: probability} per row (softmax of the scores)."""
        S = self.scores(X)
        P = np.exp(S - S.max(1, keepdims=True))
        P /= P.sum(1, keepdims=True)
        return [dict(zip(self.classes, map(float, row))) for row in P]

    def to_dict(self):
        return {"kind": self.kind, "C": self.C, "classes": self.classes, "mean": self.mean.tolist(),
                "scale": self.scale.tolist(), "coef": self.coef.tolist(), "bias": self.bias.tolist()}

    @classmethod
    def from_dict(cls, d):
        m = cls(d.get("C", 1.0))
        m.classes = list(d["classes"])
        m.mean, m.scale = np.asarray(d["mean"], float), np.asarray(d["scale"], float)
        m.coef, m.bias = np.asarray(d["coef"], float), np.asarray(d["bias"], float)
        return m


class Tree:
    kind = "tree"

    def __init__(self, max_depth=4, min_leaf=2):
        self.max_depth, self.min_leaf = int(max_depth), int(min_leaf)

    def fit(self, X, y):
        X = np.asarray(X, float)
        y = np.asarray(y, int)
        self.classes = sorted(set(y.tolist()))
        yi = np.searchsorted(self.classes, y)
        self.feature, self.threshold, self.left, self.right, self.value = [], [], [], [], []
        self._grow(X, yi, 0)
        return self

    def _node(self, counts):
        self.feature.append(-1)
        self.threshold.append(0.0)
        self.left.append(-1)
        self.right.append(-1)
        self.value.append(counts.tolist())
        return len(self.feature) - 1

    def _grow(self, X, yi, depth):
        counts = np.bincount(yi, minlength=len(self.classes))
        node = self._node(counts)
        if depth >= self.max_depth or len(yi) < 2 * self.min_leaf or (counts > 0).sum() <= 1:
            return node
        best = None                                   # (impurity, feature, threshold)
        n = len(yi)
        for j in range(X.shape[1]):
            order = np.argsort(X[:, j], kind="stable")
            xs, ys = X[order, j], yi[order]
            onehot = np.eye(len(self.classes))[ys]
            left = np.cumsum(onehot, 0)[:-1]
            right = counts - left
            nl = np.arange(1, n)
            nr = n - nl
            gini = (nl * (1 - ((left / nl[:, None]) ** 2).sum(1)) + nr * (1 - ((right / nr[:, None]) ** 2).sum(1))) / n
            ok = (xs[1:] > xs[:-1]) & (nl >= self.min_leaf) & (nr >= self.min_leaf)
            if not ok.any():
                continue
            gini = np.where(ok, gini, np.inf)
            k = int(np.argmin(gini))
            if best is None or gini[k] < best[0] - 1e-12:
                best = (gini[k], j, (xs[k] + xs[k + 1]) / 2)
        parent = 1 - ((counts / n) ** 2).sum()
        if best is None or best[0] >= parent - 1e-12:
            return node
        _, j, t = best
        mask = X[:, j] <= t
        self.feature[node], self.threshold[node] = j, float(t)
        self.left[node] = self._grow(X[mask], yi[mask], depth + 1)
        self.right[node] = self._grow(X[~mask], yi[~mask], depth + 1)
        return node

    def leaf(self, x):
        n = 0
        while self.feature[n] >= 0:
            n = self.left[n] if x[self.feature[n]] <= self.threshold[n] else self.right[n]
        return n

    def predict(self, X):
        return np.asarray([self.classes[int(np.argmax(self.value[self.leaf(x)]))] for x in np.asarray(X, float)])

    def proba(self, X):
        """{class: share of the training rounds in the leaf} per row."""
        out = []
        for x in np.asarray(X, float):
            v = np.asarray(self.value[self.leaf(x)], float)
            out.append(dict(zip(self.classes, map(float, v / v.sum()))))
        return out

    def to_dict(self):
        return {"kind": self.kind, "max_depth": self.max_depth, "min_leaf": self.min_leaf, "classes": self.classes,
                "feature": self.feature, "threshold": self.threshold, "left": self.left, "right": self.right,
                "value": self.value}

    @classmethod
    def from_dict(cls, d):
        m = cls(d.get("max_depth", 4), d.get("min_leaf", 2))
        for k in ("classes", "feature", "threshold", "left", "right", "value"):
            setattr(m, k, list(d[k]))
        return m


def from_dict(d):
    return {"logreg": LogReg, "tree": Tree}[d["kind"]].from_dict(d)


def make(kind, **params):
    if kind == "logreg":
        return LogReg(params.get("C", 1.0))
    if kind == "tree":
        return Tree(params.get("max_depth", 4), params.get("min_leaf", 2))
    raise ValueError(f"unknown model kind {kind!r}")
