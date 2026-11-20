"""Small, dependency-free linear algebra helpers used by the factor engine."""
from __future__ import annotations

import math
from typing import Iterable, Sequence


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: Sequence[float], ddof: int = 1) -> float:
    n = len(values)
    if n <= ddof:
        return 0.0
    mu = mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - ddof))


def variance(values: Sequence[float], ddof: int = 1) -> float:
    return stdev(values, ddof=ddof) ** 2


def zscore(values: Sequence[float]) -> list[float]:
    mu = mean(values)
    sd = stdev(values)
    if sd <= 1e-15:
        return [0.0 for _ in values]
    return [(v - mu) / sd for v in values]


def clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def rankdata(values: Sequence[float]) -> list[float]:
    """Average ranks, ties share the mean rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = rank
        i = j + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    mx, my = mean(x), mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 1e-15 or syy <= 1e-15:
        return 0.0
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / math.sqrt(sxx * syy)


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    return pearson(rankdata(x), rankdata(y))


def transpose(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    if not matrix:
        return []
    return [list(row) for row in zip(*matrix)]


def matmul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> list[list[float]]:
    if not a or not b:
        return []
    bt = transpose(b)
    return [[sum(x * y for x, y in zip(row, col)) for col in bt] for row in a]


def solve_linear(a: Sequence[Sequence[float]], b: Sequence[float]) -> list[float]:
    """Gaussian elimination with partial pivoting. A is copied."""
    n = len(a)
    if n == 0 or len(b) != n:
        raise ValueError("shape mismatch")
    m = [list(row) + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-14:
            raise ValueError("singular matrix")
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                m[r][j] -= factor * m[col][j]
    return [m[i][n] for i in range(n)]


def cholesky_solve(a: Sequence[Sequence[float]], b: Sequence[float]) -> list[float]:
    n = len(a)
    low = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            acc = a[i][j] - sum(low[i][k] * low[j][k] for k in range(j))
            if i == j:
                if acc <= 1e-14:
                    raise ValueError("matrix is not positive definite")
                low[i][j] = math.sqrt(acc)
            else:
                low[i][j] = acc / low[j][j]
    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(low[i][k] * y[k] for k in range(i))) / low[i][i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (y[i] - sum(low[k][i] * x[k] for k in range(i + 1, n))) / low[i][i]
    return x


def invert_matrix(a: Sequence[Sequence[float]]) -> list[list[float]]:
    n = len(a)
    cols = []
    for j in range(n):
        unit = [1.0 if i == j else 0.0 for i in range(n)]
        cols.append(solve_linear(a, unit))
    return transpose(cols)


def ols(
    rows: Sequence[Sequence[float]],
    y: Sequence[float],
    weights: Sequence[float] | None = None,
    ridge: float = 1e-8,
) -> dict:
    """Weighted least squares with a tiny ridge term.

    Returns beta, residuals, fitted values and R-squared on the weighted data.
    """
    n = len(rows)
    if n == 0 or len(y) != n:
        raise ValueError("empty design matrix")
    k = len(rows[0])
    if any(len(row) != k for row in rows):
        raise ValueError("ragged design matrix")
    w = list(weights) if weights is not None else [1.0] * n
    if len(w) != n:
        raise ValueError("weight length mismatch")
    sw = [math.sqrt(max(v, 1e-12)) for v in w]
    xs = [[row[j] * sw[i] for j in range(k)] for i, row in enumerate(rows)]
    ys = [y[i] * sw[i] for i in range(n)]
    xtx = [[sum(xs[r][i] * xs[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    xty = [sum(xs[r][i] * ys[r] for r in range(n)) for i in range(k)]
    for attempt in range(8):
        a = [row[:] for row in xtx]
        penalty = ridge * (10 ** attempt)
        for i in range(k):
            a[i][i] += penalty
        try:
            beta = cholesky_solve(a, xty)
            break
        except ValueError:
            continue
    else:
        beta = [0.0] * k
    fitted = [sum(row[j] * beta[j] for j in range(k)) for row in rows]
    resid = [y[i] - fitted[i] for i in range(n)]
    wy = mean(ys)
    ss_res = sum((ys[i] - sum(rows[i][j] * beta[j] * sw[i] for j in range(k))) ** 2 for i in range(n))
    ss_tot = sum((v - wy) ** 2 for v in ys)
    r2 = 0.0 if ss_tot <= 1e-15 else 1.0 - ss_res / ss_tot
    return {
        "beta": beta,
        "fitted": fitted,
        "residuals": resid,
        "r2": r2,
        "n": n,
        "k": k,
    }


def jacobi_eigh(matrix: Sequence[Sequence[float]], tol: float = 1e-14, max_sweeps: int = 80):
    """Jacobi eigenvalue decomposition for a small symmetric matrix.

    Returns (eigenvalues, eigenvectors) where eigenvectors are columns.
    """
    n = len(matrix)
    a = [list(row) for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(max_sweeps):
        off = sum(a[i][j] ** 2 for i in range(n) for j in range(i + 1, n))
        if off < tol * tol:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                apq = a[p][q]
                if abs(apq) < tol:
                    continue
                tau = (a[q][q] - a[p][p]) / (2.0 * apq)
                if tau >= 0:
                    t = 1.0 / (tau + math.sqrt(1.0 + tau * tau))
                else:
                    t = -1.0 / (-tau + math.sqrt(1.0 + tau * tau))
                c = 1.0 / math.sqrt(1.0 + t * t)
                s = t * c
                for k in range(n):
                    if k == p or k == q:
                        continue
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = a[p][k] = c * akp - s * akq
                    a[k][q] = a[q][k] = s * akp + c * akq
                app, aqq = a[p][p], a[q][q]
                a[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
                a[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
                a[p][q] = a[q][p] = 0.0
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    return [a[i][i] for i in range(n)], v


def inv_sqrt_spd(matrix: Sequence[Sequence[float]], ridge: float = 1e-8) -> list[list[float]]:
    """Inverse square root of a symmetric positive semi-definite matrix."""
    vals, vecs = jacobi_eigh(matrix)
    n = len(matrix)
    inv = [0.0] * n
    for i, value in enumerate(vals):
        if value <= ridge:
            value = ridge
        inv[i] = 1.0 / math.sqrt(value)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            total = sum(vecs[i][k] * inv[k] * vecs[j][k] for k in range(n))
            out[i][j] = out[j][i] = total
    return out


def correlation(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    """Correlation matrix from an n-by-k column matrix."""
    if not matrix:
        return []
    n = len(matrix)
    k = len(matrix[0])
    cols = [[matrix[i][j] for i in range(n)] for j in range(k)]
    out = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            c = pearson(cols[i], cols[j])
            out[i][j] = out[j][i] = c
    return out


def vif_from_corr(corr: Sequence[Sequence[float]]) -> list[float]:
    k = len(corr)
    if k == 0:
        return []
    try:
        inv = invert_matrix(corr)
    except ValueError:
        inv = invert_matrix([[corr[i][j] + (1e-6 if i == j else 0.0) for j in range(k)] for i in range(k)])
    return [max(inv[i][i], 1.0) for i in range(k)]


def max_offdiag_corr(corr: Sequence[Sequence[float]]) -> float:
    k = len(corr)
    if k < 2:
        return 0.0
    return max(abs(corr[i][j]) for i in range(k) for j in range(i + 1, k))


def condition_number(matrix: Sequence[Sequence[float]]) -> float:
    vals, _ = jacobi_eigh(matrix)
    high = max(vals)
    low = min(vals)
    if low <= 1e-15:
        return float("inf")
    return high / low


def cumulative(values: Iterable[float], start: float = 1.0) -> list[float]:
    out = []
    value = start
    for item in values:
        value *= 1.0 + item
        out.append(value)
    return out


def max_drawdown(values: Sequence[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst

