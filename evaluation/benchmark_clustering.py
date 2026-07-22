"""
benchmark_clustering.py
========================
Benchmarks the DOHS custom DBSCAN implementation against scikit-learn's
DBSCAN across multiple dataset sizes, measuring:
  - Adjusted Rand Index  (ARI)  — clustering accuracy vs. ground truth
  - Adjusted Mutual Information (AMI) — information-based accuracy
  - Execution time (ms)          — wall-clock performance
  - Peak memory usage (KB)       — memory overhead

The production codebase does NOT import scikit-learn.
scikit-learn is only installed in requirements-dev.txt and only used here.

Usage:
    # 1. Install dev deps first
    pip install -r requirements-dev.txt

    # 2. Generate a dataset (or use an existing one)
    python evaluation/generate_synthetic_outbreaks.py

    # 3. Run the benchmark
    python evaluation/benchmark_clustering.py
    python evaluation/benchmark_clustering.py --dataset evaluation/data/synthetic_outbreak_20240101_120000.json
    python evaluation/benchmark_clustering.py --eps 10 --min_samples 3 --trials 5
"""

import argparse
import csv
import json
import math
import os
import sys
import time
import tracemalloc
from datetime import datetime
from typing import List, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Adjust sys.path so we can import the production DBSCAN from app/core/
# We import from core/clustering.py DIRECTLY — not from analysis_route.py —
# because analysis_route.py imports core.db which triggers DB engine creation.
# core/clustering.py is pure Python with no DB or FastAPI dependencies.
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, "app")
sys.path.insert(0, APP_DIR)

# Production DBSCAN functions — pure spatial math, no DB dependency
from core.clustering import dbscan as custom_dbscan, haversine_distance

# ---------------------------------------------------------------------------
# scikit-learn DBSCAN — only imported here in the benchmark script
# ---------------------------------------------------------------------------
try:
    from sklearn.cluster import DBSCAN as SklearnDBSCAN
    from sklearn.metrics import adjusted_rand_score, adjusted_mutual_info_score
    SKLEARN_AVAILABLE = True
except ImportError:
    print("ERROR: scikit-learn not found. Run: pip install -r requirements-dev.txt")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Haversine distance matrix for scikit-learn (fair comparison)
# ---------------------------------------------------------------------------
EARTH_RADIUS_KM = 6371.0088


def build_haversine_distance_matrix(points: np.ndarray) -> np.ndarray:
    """
    Pre-compute an N×N pairwise distance matrix using the same Haversine
    formula as the custom implementation, so scikit-learn uses identical
    distance semantics.
    """
    n = len(points)
    dist_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_distance(points[i][0], points[i][1], points[j][0], points[j][1])
            dist_matrix[i][j] = d
            dist_matrix[j][i] = d
    return dist_matrix


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------

def run_custom_dbscan(points: np.ndarray, eps_km: float, min_samples: int, n_trials: int) -> dict:
    """Run the custom DBSCAN n_trials times and return timing + memory stats."""
    times_ms = []
    peak_kb = []
    labels = None

    for _ in range(n_trials):
        tracemalloc.start()
        t0 = time.perf_counter()
        labels = custom_dbscan(points, eps_km=eps_km, min_samples=min_samples)
        t1 = time.perf_counter()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times_ms.append((t1 - t0) * 1000)
        peak_kb.append(peak / 1024)

    return {
        "labels": labels,
        "mean_time_ms": round(float(np.mean(times_ms)), 3),
        "min_time_ms": round(float(np.min(times_ms)), 3),
        "max_time_ms": round(float(np.max(times_ms)), 3),
        "peak_memory_kb": round(float(np.mean(peak_kb)), 2),
    }


def run_sklearn_dbscan(dist_matrix: np.ndarray, eps_km: float, min_samples: int, n_trials: int) -> dict:
    """Run scikit-learn DBSCAN n_trials times using precomputed distance matrix."""
    times_ms = []
    peak_kb = []
    labels = None

    for _ in range(n_trials):
        tracemalloc.start()
        t0 = time.perf_counter()
        clf = SklearnDBSCAN(eps=eps_km, min_samples=min_samples, metric="precomputed")
        labels = clf.fit_predict(dist_matrix)
        t1 = time.perf_counter()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times_ms.append((t1 - t0) * 1000)
        peak_kb.append(peak / 1024)

    return {
        "labels": labels,
        "mean_time_ms": round(float(np.mean(times_ms)), 3),
        "min_time_ms": round(float(np.min(times_ms)), 3),
        "max_time_ms": round(float(np.max(times_ms)), 3),
        "peak_memory_kb": round(float(np.mean(peak_kb)), 2),
    }


def compute_accuracy_metrics(true_labels: list, custom_labels: np.ndarray, sklearn_labels: np.ndarray) -> dict:
    """Compute ARI and AMI for both implementations against ground truth."""
    true = np.array(true_labels)
    return {
        "custom_ari": round(float(adjusted_rand_score(true, custom_labels)), 4),
        "custom_ami": round(float(adjusted_mutual_info_score(true, custom_labels)), 4),
        "sklearn_ari": round(float(adjusted_rand_score(true, sklearn_labels)), 4),
        "sklearn_ami": round(float(adjusted_mutual_info_score(true, sklearn_labels)), 4),
        "label_agreement_pct": round(
            float(np.mean(
                # Remap labels to handle different cluster ordering
                adjusted_rand_score(custom_labels, sklearn_labels)
            ) * 100), 2
        ),
    }


def cluster_summary(labels: np.ndarray) -> dict:
    unique = set(labels.tolist())
    n_clusters = len([l for l in unique if l != -1])
    n_noise = int(np.sum(labels == -1))
    return {"n_clusters_found": n_clusters, "n_noise_points": n_noise}


# ---------------------------------------------------------------------------
# Dataset loading and sub-sampling
# ---------------------------------------------------------------------------

def load_dataset(path: str) -> Tuple[np.ndarray, list]:
    """Load JSON dataset, return (points_array, true_labels)."""
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    points = np.array([[r["lat"], r["lon"]] for r in records])
    true_labels = [r["true_cluster"] for r in records]
    return points, true_labels


def subsample(points: np.ndarray, true_labels: list, n: int, seed: int = 42):
    """Randomly subsample n points from the dataset."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(points), size=min(n, len(points)), replace=False)
    return points[idx], [true_labels[i] for i in idx]


# ---------------------------------------------------------------------------
# Results output
# ---------------------------------------------------------------------------

def print_results_table(results: list):
    header = (
        f"{'Size':>6} | {'Custom ARI':>10} | {'Sklearn ARI':>11} | "
        f"{'Custom ms':>10} | {'Sklearn ms':>10} | "
        f"{'Custom KB':>10} | {'Sklearn KB':>10} | {'Agreement%':>10}"
    )
    sep = "-" * len(header)
    print("\n" + sep)
    print(header)
    print(sep)
    for r in results:
        print(
            f"{r['n_points']:>6} | {r['custom_ari']:>10.4f} | {r['sklearn_ari']:>11.4f} | "
            f"{r['custom_mean_ms']:>10.2f} | {r['sklearn_mean_ms']:>10.2f} | "
            f"{r['custom_peak_kb']:>10.1f} | {r['sklearn_peak_kb']:>10.1f} | "
            f"{r['label_agreement_pct']:>10.2f}"
        )
    print(sep + "\n")


def save_csv(results: list, output_dir: str = "evaluation/results"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"clustering_benchmark_{timestamp}.csv")
    fieldnames = list(results[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    return path


# ---------------------------------------------------------------------------
# Main benchmark loop
# ---------------------------------------------------------------------------

def run_benchmark(
    dataset_path: str,
    eps_km: float = 10.0,
    min_samples: int = 3,
    n_trials: int = 5,
    sizes: List[int] = None,
):
    if sizes is None:
        sizes = [50, 100, 250, 500]

    print(f"\n{'='*65}")
    print(f"  DOHS DBSCAN Benchmark -- Custom vs. scikit-learn")
    print(f"{'='*65}")
    print(f"  Dataset    : {dataset_path}")
    print(f"  eps_km     : {eps_km} km")
    print(f"  min_samples: {min_samples}")
    print(f"  Trials     : {n_trials} per size")
    print(f"  Sizes      : {sizes}")
    print(f"{'='*65}\n")

    all_points, all_true_labels = load_dataset(dataset_path)
    print(f"  Loaded {len(all_points)} total records from dataset.\n")

    results = []

    for n in sizes:
        if n > len(all_points):
            print(f"  [SKIP] Requested size {n} > dataset size {len(all_points)}")
            continue

        print(f"  Running size = {n}…", end=" ", flush=True)
        points, true_labels = subsample(all_points, all_true_labels, n)

        # Build distance matrix once (shared by sklearn)
        dist_matrix = build_haversine_distance_matrix(points)

        # --- Custom DBSCAN ---
        custom_result = run_custom_dbscan(points, eps_km, min_samples, n_trials)

        # --- scikit-learn DBSCAN ---
        sklearn_result = run_sklearn_dbscan(dist_matrix, eps_km, min_samples, n_trials)

        # --- Accuracy metrics ---
        acc = compute_accuracy_metrics(true_labels, custom_result["labels"], sklearn_result["labels"])

        custom_summary = cluster_summary(custom_result["labels"])
        sklearn_summary = cluster_summary(sklearn_result["labels"])

        row = {
            "n_points": n,
            "eps_km": eps_km,
            "min_samples": min_samples,
            # Accuracy
            "custom_ari": acc["custom_ari"],
            "custom_ami": acc["custom_ami"],
            "sklearn_ari": acc["sklearn_ari"],
            "sklearn_ami": acc["sklearn_ami"],
            "label_agreement_pct": acc["label_agreement_pct"],
            # Timing
            "custom_mean_ms": custom_result["mean_time_ms"],
            "custom_min_ms": custom_result["min_time_ms"],
            "custom_max_ms": custom_result["max_time_ms"],
            "sklearn_mean_ms": sklearn_result["mean_time_ms"],
            "sklearn_min_ms": sklearn_result["min_time_ms"],
            "sklearn_max_ms": sklearn_result["max_time_ms"],
            # Memory
            "custom_peak_kb": custom_result["peak_memory_kb"],
            "sklearn_peak_kb": sklearn_result["peak_memory_kb"],
            # Cluster counts
            "custom_clusters_found": custom_summary["n_clusters_found"],
            "custom_noise": custom_summary["n_noise_points"],
            "sklearn_clusters_found": sklearn_summary["n_clusters_found"],
            "sklearn_noise": sklearn_summary["n_noise_points"],
        }
        results.append(row)
        print(f"done (Custom ARI={acc['custom_ari']:.4f}, sklearn ARI={acc['sklearn_ari']:.4f})")

    print_results_table(results)
    csv_path = save_csv(results)
    print(f"  [OK] Results saved to: {csv_path}\n")
    return results


# ---------------------------------------------------------------------------
# CLI Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark DOHS custom DBSCAN against scikit-learn DBSCAN."
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Path to a synthetic dataset JSON file. If not provided, auto-generates one.",
    )
    parser.add_argument("--eps", type=float, default=10.0, help="Neighbourhood radius in km (default: 10.0)")
    parser.add_argument("--min_samples", type=int, default=3, help="Minimum points per cluster (default: 3)")
    parser.add_argument("--trials", type=int, default=5, help="Number of timing trials per size (default: 5)")
    parser.add_argument(
        "--sizes",
        type=str,
        default="50,100,250,500",
        help="Comma-separated dataset sizes to benchmark (default: 50,100,250,500)",
    )
    args = parser.parse_args()

    sizes = [int(s.strip()) for s in args.sizes.split(",")]

    # Auto-generate a dataset if none provided
    if args.dataset is None:
        print("  No dataset provided — generating one with default parameters…")
        # Import inline to avoid circular dependency issues when called directly
        from generate_synthetic_outbreaks import generate_dataset, save_dataset
        dataset = generate_dataset(n_clusters=4, points_per_cluster=max(sizes) // 4 + 5,
                                   n_noise_points=20, seed=42)
        dataset_path = save_dataset(dataset, "evaluation/data")
        print(f"  Generated dataset saved to: {dataset_path}")
    else:
        dataset_path = args.dataset

    run_benchmark(
        dataset_path=dataset_path,
        eps_km=args.eps,
        min_samples=args.min_samples,
        n_trials=args.trials,
        sizes=sizes,
    )
