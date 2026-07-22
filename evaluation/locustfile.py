"""
locustfile.py
=============
Load-test configuration for the DOHS backend — Research Question 2.

Models realistic health-worker usage patterns:
  - Login
  - Submit a health report (write)
  - Fetch personal dashboard (read)
  - Fetch integrated cases feed (read)

Read:write weighting = 3:1 (realistic field usage assumption)

Usage:
    pip install locust

    # Interactive web UI (opens browser at localhost:8089)
    locust -f evaluation/locustfile.py --host http://127.0.0.1:8000

    # Headless — 10 concurrent users, ramp 2/s, run for 2 minutes
    locust -f evaluation/locustfile.py --headless -u 10 -r 2 -t 2m --host http://127.0.0.1:8000

    # Headless — higher concurrency scenario
    locust -f evaluation/locustfile.py --headless -u 50 -r 5 -t 2m --host http://127.0.0.1:8000 --html evaluation/results/load_test_50u.html
"""

import json
import random

from locust import HttpUser, between, task

# ---------------------------------------------------------------------------
# Test credentials — ensure this test user exists in the database
# before running load tests. Use POST /api/v1/health/signup to create them.
# ---------------------------------------------------------------------------
TEST_EMAIL = "admin@dohs.com"
TEST_PASSWORD = "admin123"

# ---------------------------------------------------------------------------
# Sample report payloads — randomised to avoid caching effects
# ---------------------------------------------------------------------------
DISEASES = ["Malaria", "Cholera", "Typhoid", "Dengue", "Meningitis"]
STATES = ["FCT", "Lagos", "Kano", "Enugu", "Kaduna"]
LGAS = ["Municipal", "Ikeja", "Nassarawa", "Enugu North", "Zaria"]
CLASSIFICATIONS = ["Suspected", "Probable", "Confirmed"]
OUTCOMES = ["Alive", "Dead", "Unknown"]

# Approximate Nigeria centre coordinates with slight jitter per request
BASE_LAT = 9.0765
BASE_LON = 7.3986


def make_report_payload() -> dict:
    """Generate a randomised but schema-valid report payload."""
    return {
        "disease": random.choice(DISEASES),
        "classification": random.choice(CLASSIFICATIONS),
        "outcome": random.choice(OUTCOMES),
        "state": random.choice(STATES),
        "lga": random.choice(LGAS),
        "health_facility": "Load Test Clinic",
        "region": "North Central",
        "latitude": round(BASE_LAT + random.uniform(-2.0, 2.0), 6),
        "longitude": round(BASE_LON + random.uniform(-2.0, 2.0), 6),
        "date_of_onset": "2024-06-01T00:00:00",
        "date_of_confirmation": None,
        "reporting_source": "Locust Load Test",
        "age": random.randint(5, 70),
        "sex": random.choice(["Male", "Female"]),
        "symptoms": "fever, headache",
        "risk_factors": "community exposure",
        "category": "Human",
    }


# ---------------------------------------------------------------------------
# Locust User
# ---------------------------------------------------------------------------

class HealthWorkerUser(HttpUser):
    """
    Simulates a field health worker who logs in once per session then
    alternates between submitting reports (writes) and reading dashboards.
    """
    # Wait between 1 and 3 seconds between tasks — realistic think time
    wait_time = between(1, 3)

    def on_start(self):
        """Called when a virtual user starts — authenticate once."""
        self.token = None
        self._login()

    def _login(self):
        """Authenticate and store the Bearer token."""
        with self.client.post(
            "/api/v1/health/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            catch_response=True,
            name="POST /health/login",
        ) as resp:
            if resp.status_code == 200:
                self.token = resp.json().get("access_token")
                resp.success()
            else:
                self.token = None
                resp.failure(f"Login failed: {resp.status_code}")

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    # -----------------------------------------------------------------------
    # Write task — weighted 1 (1 out of every 4 task executions)
    # -----------------------------------------------------------------------
    @task(1)
    def submit_health_report(self):
        """POST a new incident report to /reports/health."""
        if not self.token:
            self._login()
            return

        payload = make_report_payload()
        with self.client.post(
            "/api/v1/reports/health",
            json=payload,
            headers=self._auth_headers(),
            catch_response=True,
            name="POST /reports/health",
        ) as resp:
            if resp.status_code in (200, 201):
                resp.success()
            else:
                resp.failure(f"Report submission failed: {resp.status_code} — {resp.text[:100]}")

    # -----------------------------------------------------------------------
    # Read tasks — weighted 3 (3 out of every 4 task executions)
    # -----------------------------------------------------------------------
    @task(2)
    def view_personal_dashboard(self):
        """GET the mobile personal dashboard."""
        if not self.token:
            return

        with self.client.get(
            "/api/v1/mobile/dashboard/",
            headers=self._auth_headers(),
            catch_response=True,
            name="GET /mobile/dashboard/",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Dashboard failed: {resp.status_code}")

    @task(1)
    def view_integrated_cases(self):
        """GET the unified integrated cases feed."""
        with self.client.get(
            "/api/v1/integrated/cases",
            catch_response=True,
            name="GET /integrated/cases",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Integrated cases failed: {resp.status_code}")

    @task(1)
    def view_clusters(self):
        """GET spatial cluster detection (read-only, no auth required)."""
        with self.client.get(
            "/api/v1/analysis/clusters?radius_km=10&min_samples=3",
            catch_response=True,
            name="GET /analysis/clusters",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Cluster detection failed: {resp.status_code}")
