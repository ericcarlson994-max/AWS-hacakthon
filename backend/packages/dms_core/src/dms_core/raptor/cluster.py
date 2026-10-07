from __future__ import annotations

import warnings

import numpy as np
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture

MAX_PCA_COMPONENTS = 10
SINGLE_CLUSTER_LIMIT = 3


def _reduce(matrix: np.ndarray, seed: int) -> np.ndarray:
    components = min(MAX_PCA_COMPONENTS, matrix.shape[0] - 1, matrix.shape[1])
    if components < 1:
        return matrix
    return PCA(n_components=components, random_state=seed).fit_transform(matrix)


def cluster_vectors(vectors: list[list[float]], max_k: int = 8, seed: int = 0) -> list[list[int]]:
    count = len(vectors)
    if count == 0:
        return []
    if count <= SINGLE_CLUSTER_LIMIT:
        return [list(range(count))]
    matrix = np.asarray(vectors, dtype=float)
    reduced = _reduce(matrix, seed)
    upper = min(max_k, (count // 3) or 2)
    upper = max(2, min(upper, count - 1))
    best_labels: np.ndarray | None = None
    best_bic = float("inf")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for k in range(2, upper + 1):
            try:
                model = GaussianMixture(n_components=k, covariance_type="diag", random_state=seed, reg_covar=1e-5)
                model.fit(reduced)
                bic = model.bic(reduced)
            except ValueError:
                continue
            if bic < best_bic:
                best_bic = bic
                best_labels = model.predict(reduced)
    if best_labels is None:
        return [list(range(count))]
    groups: dict[int, list[int]] = {}
    for index, label in enumerate(best_labels.tolist()):
        groups.setdefault(int(label), []).append(index)
    return [members for _, members in sorted(groups.items(), key=lambda item: item[1][0]) if members]
