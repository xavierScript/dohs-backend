"""
generate_synthetic_outbreaks.py
================================
Generates synthetic spatial disease outbreak datasets with known ground-truth
cluster labels for use in benchmarking the custom DBSCAN implementation.

All coordinates are bounded within Nigeria's geographic extent:
  Latitude:  4.0°N  to 14.0°N
  Longitude: 2.7°E  to 14.7°E

Usage:
    python evaluation/generate_synthetic_outbreaks.py
    python evaluation/generate_synthetic_outbreaks.py --n_clusters 5 --points_per_cluster 30 --noise 20 --seed 99
"""

import argparse
import json
import math
import os
import random
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Nigeria bounding box
# ---------------------------------------------------------------------------
NG_LAT_MIN, NG_LAT_MAX = 4.0, 14.0
NG_LON_MIN, NG_LON_MAX = 2.7, 14.7

# ---------------------------------------------------------------------------
# Disease catalogue (realistic for West Africa)
# ---------------------------------------------------------------------------
DISEASES = ["Malaria", "Cholera", "Lassa Fever", "Meningitis", "Typhoid", "Yellow Fever"]
CLASSIFICATIONS = ["Suspected", "Probable", "Confirmed"]
OUTCOMES = ["Alive", "Dead", "Unknown"]
CATEGORIES = ["Human", "Animal", "Environmental"]


def km_to_degrees(km: float) -> float:
    """
    Approximate conversion from kilometres to decimal degrees.
    1 degree ≈ 111.32 km at the equator; Nigeria is near-equatorial so
    this approximation is acceptable for benchmark purposes.
    """
    return km / 111.32


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def random_date(start: datetime, spread_days: int, rng: random.Random) -> str:
    delta = timedelta(days=rng.randint(0, spread_days))
    return (start + delta).strftime("%Y-%m-%dT%H:%M:%S")


def generate_cluster_centre(rng: random.Random) -> tuple:
    """Pick a random cluster centre inside Nigeria, away from edges."""
    lat = rng.uniform(NG_LAT_MIN + 1.0, NG_LAT_MAX - 1.0)
    lon = rng.uniform(NG_LON_MIN + 1.0, NG_LON_MAX - 1.0)
    return lat, lon


def generate_point_near(centre_lat: float, centre_lon: float,
                        spread_km: float, rng: random.Random) -> tuple:
    """
    Generate a point drawn from a bivariate Gaussian centred on
    (centre_lat, centre_lon) with standard deviation = spread_km.
    Uses Box-Muller transform to avoid importing numpy here.
    """
    import math
    # Box-Muller
    u1, u2 = rng.random(), rng.random()
    z0 = math.sqrt(-2.0 * math.log(u1 + 1e-10)) * math.cos(2 * math.pi * u2)
    z1 = math.sqrt(-2.0 * math.log(u1 + 1e-10)) * math.sin(2 * math.pi * u2)

    spread_deg = km_to_degrees(spread_km)
    lat = clamp(centre_lat + z0 * spread_deg, NG_LAT_MIN, NG_LAT_MAX)
    lon = clamp(centre_lon + z1 * spread_deg, NG_LON_MIN, NG_LON_MAX)
    return lat, lon


def generate_dataset(
    n_clusters: int = 4,
    points_per_cluster: int = 20,
    cluster_spread_km: float = 5.0,
    n_noise_points: int = 15,
    seed: int = 42,
    start_date: datetime = None,
    spread_days: int = 30,
) -> list:
    """
    Build a list of synthetic case records with ground-truth cluster labels.

    Returns:
        List[dict] — each dict has the structure:
        {
          "lat": float,
          "lon": float,
          "true_cluster": int,   # -1 = noise
          "disease": str,
          "classification": str,
          "outcome": str,
          "category": str,
          "reported_at": str,    # ISO 8601
        }
    """
    rng = random.Random(seed)
    if start_date is None:
        start_date = datetime(2024, 1, 1)

    records = []

    # --- Clustered points ---
    for cluster_id in range(n_clusters):
        centre_lat, centre_lon = generate_cluster_centre(rng)
        # All points in the same cluster share a disease to be realistic
        disease = rng.choice(DISEASES)

        for _ in range(points_per_cluster):
            lat, lon = generate_point_near(centre_lat, centre_lon, cluster_spread_km, rng)
            records.append({
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "true_cluster": cluster_id,
                "disease": disease,
                "classification": rng.choice(CLASSIFICATIONS),
                "outcome": rng.choice(OUTCOMES),
                "category": rng.choice(CATEGORIES),
                "reported_at": random_date(start_date, spread_days, rng),
            })

    # --- Noise points (spread randomly across Nigeria) ---
    for _ in range(n_noise_points):
        lat = rng.uniform(NG_LAT_MIN, NG_LAT_MAX)
        lon = rng.uniform(NG_LON_MIN, NG_LON_MAX)
        records.append({
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "true_cluster": -1,
            "disease": rng.choice(DISEASES),
            "classification": rng.choice(CLASSIFICATIONS),
            "outcome": rng.choice(OUTCOMES),
            "category": rng.choice(CATEGORIES),
            "reported_at": random_date(start_date, spread_days, rng),
        })

    # Shuffle so noise and cluster points are interleaved (realistic)
    rng.shuffle(records)
    return records


def save_dataset(records: list, output_dir: str = "evaluation/data") -> str:
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"synthetic_outbreak_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    return path


def print_summary(records: list, n_clusters: int, n_noise: int):
    print("\n" + "=" * 55)
    print("  Synthetic Outbreak Dataset — Generation Summary")
    print("=" * 55)
    print(f"  Total records        : {len(records)}")
    print(f"  Defined clusters     : {n_clusters}")
    print(f"  Noise points         : {n_noise}")
    cluster_counts = {}
    for r in records:
        cluster_counts[r["true_cluster"]] = cluster_counts.get(r["true_cluster"], 0) + 1
    for cid in sorted(cluster_counts):
        label = f"Cluster {cid}" if cid >= 0 else "Noise"
        print(f"  {label:<20}: {cluster_counts[cid]} points")
    print("=" * 55)


# ---------------------------------------------------------------------------
# CLI Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate synthetic spatial disease outbreak data for DBSCAN benchmarking."
    )
    parser.add_argument("--n_clusters", type=int, default=4, help="Number of true outbreak clusters (default: 4)")
    parser.add_argument("--points_per_cluster", type=int, default=20, help="Points per cluster (default: 20)")
    parser.add_argument("--spread_km", type=float, default=5.0, help="Cluster spatial spread in km (default: 5.0)")
    parser.add_argument("--noise", type=int, default=15, help="Number of random noise points (default: 15)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default: 42)")
    parser.add_argument("--days", type=int, default=30, help="Date spread in days from 2024-01-01 (default: 30)")
    parser.add_argument("--output_dir", type=str, default="evaluation/data", help="Output directory")
    args = parser.parse_args()

    print(f"\nGenerating dataset: {args.n_clusters} clusters × {args.points_per_cluster} pts + {args.noise} noise…")

    dataset = generate_dataset(
        n_clusters=args.n_clusters,
        points_per_cluster=args.points_per_cluster,
        cluster_spread_km=args.spread_km,
        n_noise_points=args.noise,
        seed=args.seed,
        spread_days=args.days,
    )

    output_path = save_dataset(dataset, args.output_dir)
    print_summary(dataset, args.n_clusters, args.noise)
    print(f"\n  ✅ Saved to: {output_path}\n")
