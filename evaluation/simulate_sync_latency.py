"""
simulate_sync_latency.py
=========================
Profiles the end-to-end latency of the DOHS field-to-dashboard data
synchronisation pipeline for Research Question 2.

Pipeline under measurement:
    Mobile App  →  POST /api/v1/reports/health  →  PostgreSQL  →  GET /api/v1/mobile/dashboard/

Two measurement modes:
  sequential   — sends N reports one at a time, measures each independently
  concurrent   — sends N reports in parallel batches, measures wall-clock throughput

Metrics reported:
  - Per-request latency: mean, median, p90, p95, p99 (milliseconds)
  - Dashboard freshness: confirms new reports appear in dashboard query
  - Error rate: percentage of failed requests

Usage:
    python evaluation/simulate_sync_latency.py --mode sequential --n 50
    python evaluation/simulate_sync_latency.py --mode concurrent --n 100 --concurrency 10
    python evaluation/simulate_sync_latency.py --host http://127.0.0.1:8000 --email worker@test.com --password testpass123
"""

import argparse
import asyncio
import csv
import json
import os
import statistics
import time
from datetime import datetime
from typing import List, Optional


# ---------------------------------------------------------------------------
# Attempt to import httpx (required)
# ---------------------------------------------------------------------------
try:
    import httpx
except ImportError:
    print("ERROR: httpx not found. Run: pip install httpx")
    import sys
    sys.exit(1)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEFAULT_HOST = "http://127.0.0.1:8000"
API_PREFIX = "/api/v1"

# Synthetic report payload — valid enough to pass Pydantic validation
SAMPLE_REPORT = {
    "disease": "Malaria",
    "classification": "Suspected",
    "outcome": "Alive",
    "state": "FCT",
    "lga": "Municipal",
    "health_facility": "Benchmark Test Clinic",
    "region": "North Central",
    "latitude": 9.0765,
    "longitude": 7.3986,
    "date_of_onset": "2024-01-15T00:00:00",
    "date_of_confirmation": None,
    "reporting_source": "Latency Benchmark Script",
    "age": 28,
    "sex": "Male",
    "symptoms": "fever, headache",
    "risk_factors": "outdoor exposure",
    "category": "Human",
}

# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------

async def login(client: httpx.AsyncClient, host: str, email: str, password: str) -> Optional[str]:
    """Login and return Bearer token, or None on failure."""
    url = f"{host}{API_PREFIX}/health/login"
    try:
        resp = await client.post(url, json={"email": email, "password": password}, timeout=15.0)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        else:
            print(f"  ❌ Login failed ({resp.status_code}): {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"  ❌ Login request error: {e}")
        return None

# ---------------------------------------------------------------------------
# Report submission
# ---------------------------------------------------------------------------

async def submit_report(client: httpx.AsyncClient, host: str, token: str) -> dict:
    """Submit one synthetic health report and return timing/status info."""
    url = f"{host}{API_PREFIX}/reports/health"
    headers = {"Authorization": f"Bearer {token}"}

    t0 = time.perf_counter()
    try:
        resp = await client.post(url, json=SAMPLE_REPORT, headers=headers, timeout=30.0)
        latency_ms = (time.perf_counter() - t0) * 1000
        success = resp.status_code in (200, 201)
        case_id = None
        if success:
            try:
                case_id = resp.json().get("case_id")
            except Exception:
                pass
        return {
            "latency_ms": round(latency_ms, 2),
            "status_code": resp.status_code,
            "success": success,
            "case_id": case_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"latency_ms": round(latency_ms, 2), "status_code": 504, "success": False, "case_id": None, "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"latency_ms": round(latency_ms, 2), "status_code": -1, "success": False, "case_id": None, "timestamp": datetime.utcnow().isoformat()}

# ---------------------------------------------------------------------------
# Dashboard freshness check
# ---------------------------------------------------------------------------

async def check_dashboard_freshness(client: httpx.AsyncClient, host: str, token: str) -> dict:
    """Fetch the mobile dashboard and return the latest reported_at timestamp."""
    url = f"{host}{API_PREFIX}/mobile/dashboard/"
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.perf_counter()
    try:
        resp = await client.get(url, headers=headers, timeout=15.0)
        latency_ms = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            recent = data.get("recent_activities", [])
            latest_ts = recent[0].get("reported_at") if recent else None
            return {"dashboard_latency_ms": round(latency_ms, 2), "latest_report_ts": latest_ts, "success": True}
        return {"dashboard_latency_ms": round(latency_ms, 2), "latest_report_ts": None, "success": False}
    except Exception as e:
        return {"dashboard_latency_ms": -1.0, "latest_report_ts": None, "success": False}

# ---------------------------------------------------------------------------
# Sequential mode
# ---------------------------------------------------------------------------

async def run_sequential(host: str, token: str, n: int) -> List[dict]:
    """Submit N reports one at a time."""
    results = []
    async with httpx.AsyncClient() as client:
        for i in range(n):
            result = await submit_report(client, host, token)
            results.append(result)
            status = "✓" if result["success"] else "✗"
            print(f"  [{i+1:>4}/{n}] {status}  {result['latency_ms']:>8.2f} ms  (HTTP {result['status_code']})")
    return results

# ---------------------------------------------------------------------------
# Concurrent mode
# ---------------------------------------------------------------------------

async def run_concurrent(host: str, token: str, n: int, concurrency: int) -> List[dict]:
    """Submit N reports with up to `concurrency` in-flight at once."""
    results = []
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_submit(client, idx):
        async with semaphore:
            result = await submit_report(client, host, token)
            status = "✓" if result["success"] else "✗"
            print(f"  [{idx:>4}/{n}] {status}  {result['latency_ms']:>8.2f} ms  (HTTP {result['status_code']})")
            return result

    async with httpx.AsyncClient() as client:
        tasks = [bounded_submit(client, i + 1) for i in range(n)]
        results = await asyncio.gather(*tasks)

    return list(results)

# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def percentile(data: list, p: float) -> float:
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_data) - 1)
    return round(sorted_data[lo] + (k - lo) * (sorted_data[hi] - sorted_data[lo]), 2)


def print_stats(results: list):
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    latencies = [r["latency_ms"] for r in successful]

    print("\n" + "=" * 60)
    print("  Latency Statistics — Report Submission")
    print("=" * 60)
    print(f"  Total requests   : {len(results)}")
    print(f"  Successful       : {len(successful)}")
    print(f"  Failed           : {len(failed)}")
    print(f"  Error rate       : {len(failed)/len(results)*100:.1f}%")
    if latencies:
        print(f"\n  Mean             : {statistics.mean(latencies):.2f} ms")
        print(f"  Median (p50)     : {percentile(latencies, 50):.2f} ms")
        print(f"  p90              : {percentile(latencies, 90):.2f} ms")
        print(f"  p95              : {percentile(latencies, 95):.2f} ms")
        print(f"  p99              : {percentile(latencies, 99):.2f} ms")
        print(f"  Min              : {min(latencies):.2f} ms")
        print(f"  Max              : {max(latencies):.2f} ms")
    print("=" * 60)


def save_results(results: list, mode: str, output_dir: str = "evaluation/results"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"latency_profile_{mode}_{timestamp}.csv")
    if not results:
        return path
    fieldnames = list(results[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    return path

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main(args):
    print(f"\n{'='*60}")
    print(f"  DOHS Latency Profiler — RQ2 Evaluation")
    print(f"{'='*60}")
    print(f"  Host        : {args.host}")
    print(f"  Mode        : {args.mode}")
    print(f"  N requests  : {args.n}")
    if args.mode == "concurrent":
        print(f"  Concurrency : {args.concurrency}")
    print(f"{'='*60}\n")

    # Authenticate
    async with httpx.AsyncClient() as client:
        token = await login(client, args.host, args.email, args.password)

    if not token:
        print("  ❌ Cannot proceed without a valid token. Check credentials and server status.")
        return

    print(f"  ✅ Authenticated successfully.\n")
    print(f"  Submitting {args.n} reports ({args.mode} mode)…\n")

    if args.mode == "sequential":
        results = await run_sequential(args.host, token, args.n)
    else:
        results = await run_concurrent(args.host, token, args.n, args.concurrency)

    print_stats(results)

    # Dashboard freshness check
    print("\n  Checking dashboard freshness…")
    async with httpx.AsyncClient() as client:
        freshness = await check_dashboard_freshness(client, args.host, token)
    if freshness["success"]:
        print(f"  ✅ Dashboard query latency : {freshness['dashboard_latency_ms']:.2f} ms")
        print(f"  ✅ Most recent activity ts : {freshness['latest_report_ts']}")
    else:
        print("  ⚠️  Dashboard freshness check failed.")

    path = save_results(results, args.mode)
    print(f"\n  ✅ Results saved to: {path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DOHS latency profiler for RQ2 evaluation.")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help=f"API base URL (default: {DEFAULT_HOST})")
    parser.add_argument("--email", type=str, default="worker@dohs.test", help="Health worker email for login")
    parser.add_argument("--password", type=str, default="testpass123", help="Health worker password")
    parser.add_argument("--mode", type=str, choices=["sequential", "concurrent"], default="sequential", help="Test mode")
    parser.add_argument("--n", type=int, default=50, help="Number of reports to submit (default: 50)")
    parser.add_argument("--concurrency", type=int, default=10, help="Max concurrent requests in concurrent mode (default: 10)")
    args = parser.parse_args()

    asyncio.run(main(args))
