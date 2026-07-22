"""
core/clustering.py
==================
Pure spatial clustering functions — no database dependency.

These functions are used by:
  - app/api/routes/analysis/analysis_route.py  (production API)
  - evaluation/benchmark_clustering.py         (academic benchmarking)

Keeping them here ensures the benchmark can import them without
triggering the database engine or any FastAPI application state.
"""

import numpy as np


EARTH_RADIUS_KM = 6371.0088


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Compute the great-circle distance in kilometres between two points
    on Earth using the Haversine formula.

    Args:
        lat1, lon1: coordinates of point A in decimal degrees
        lat2, lon2: coordinates of point B in decimal degrees

    Returns:
        Distance in kilometres (float)
    """
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def region_query(points: np.ndarray, idx: int, eps_km: float) -> list:
    """
    Find all point indices within eps_km of points[idx].

    Args:
        points:  (N, 2) array of [lat, lon] values
        idx:     index of the query point
        eps_km:  neighbourhood radius in kilometres

    Returns:
        List of integer indices of neighbouring points (including idx itself)
    """
    neighbours = []
    for i, _ in enumerate(points):
        if haversine_distance(points[idx][0], points[idx][1], points[i][0], points[i][1]) <= eps_km:
            neighbours.append(i)
    return neighbours


def dbscan(points: np.ndarray, eps_km: float, min_samples: int) -> np.ndarray:
    """
    Density-Based Spatial Clustering of Applications with Noise (DBSCAN).

    Custom implementation using Haversine distance — no scikit-learn dependency.
    Designed for deployment in low-resource or air-gapped environments.

    Args:
        points:      (N, 2) array of [lat, lon] values
        eps_km:      neighbourhood radius in kilometres
        min_samples: minimum number of points required to form a core point

    Returns:
        labels: np.ndarray of shape (N,)
                Cluster IDs (0-indexed integers). -1 denotes noise.
    """
    n = len(points)
    labels = [-1] * n
    visited = [False] * n
    cluster_id = 0

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True

        neighbours = region_query(points, i, eps_km)

        if len(neighbours) < min_samples:
            labels[i] = -1  # noise
        else:
            labels[i] = cluster_id
            seeds = neighbours.copy()

            while seeds:
                current = seeds.pop()
                if not visited[current]:
                    visited[current] = True
                    new_neighbours = region_query(points, current, eps_km)
                    if len(new_neighbours) >= min_samples:
                        seeds.extend(new_neighbours)
                if labels[current] == -1:
                    labels[current] = cluster_id

            cluster_id += 1

    return np.array(labels)
