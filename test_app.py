import unittest
from copy import deepcopy

import app as simulator


class AirportApiTests(unittest.TestCase):
    def setUp(self):
        self.client = simulator.app.test_client()
        with simulator.resource_lock:
            simulator.resources = deepcopy(simulator.DEFAULT_RESOURCES)
            simulator.flights = deepcopy(simulator.DEFAULT_FLIGHTS)
            simulator.pending_requests.clear()
            simulator.request_statistics.update(granted=0, rejected=0)
            simulator.activity_log.clear()

    def add(self, ident, priority=1, runways=1, gates=1):
        return self.client.post("/api/flights", json={"id": ident, "priority": priority, "max_runways": runways, "max_gates": gates})

    def test_dashboard_and_listing(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(len(self.client.get("/api/flights").get_json()), 2)

    def test_create_duplicate_and_invalid_flight(self):
        self.assertEqual(self.add("F200").status_code, 201)
        self.assertEqual(self.add("F200").status_code, 409)
        self.assertEqual(self.add("BAD", runways=-1).status_code, 400)
        self.assertEqual(self.client.post("/api/flights", data="[]", content_type="application/json").status_code, 400)

    def test_scheduler_respects_priority(self):
        with simulator.resource_lock:
            simulator.resources = {"runways": {"total": 1, "available": 1}, "gates": {"total": 1, "available": 1}}
            simulator.flights = []
        self.add("LOW", priority=3); self.add("HIGH", priority=1)
        self.client.post("/api/schedule")
        data = {f["id"]: f for f in self.client.get("/api/flights").get_json()}
        self.assertEqual(data["HIGH"]["state"], "Running")
        self.assertEqual(data["LOW"]["state"], "Waiting")

    def test_successful_request_and_statistics(self):
        response = self.client.post("/api/flights/F101/request", json={"runways": 1, "gates": 1})
        self.assertEqual(response.status_code, 200)
        stats = self.client.get("/api/statistics").get_json()
        self.assertEqual((stats["resource_requests_granted"], stats["pending_requests"]), (1, 0))
        self.assertEqual(stats["runway_utilization"], 50.0)

    def test_request_exceeding_need_and_missing_payload(self):
        self.assertEqual(self.client.post("/api/flights/F101/request", json={"runways": 2, "gates": 0}).status_code, 400)
        self.assertEqual(self.client.post("/api/flights/F101/request", json={"runways": -1, "gates": 0}).status_code, 400)
        self.assertEqual(self.client.post("/api/flights/F101/request", data="{}", content_type="application/json").status_code, 400)

    def test_pending_request_is_retried_after_release(self):
        self.client.post("/api/flights/F101/request", json={"runways": 1, "gates": 1})
        self.add("F300", priority=1, runways=2, gates=1)
        queued = self.client.post("/api/flights/F300/request", json={"runways": 2, "gates": 1})
        self.assertEqual(queued.status_code, 202)
        self.client.post("/api/flights/F101/terminate")
        flight = next(f for f in self.client.get("/api/flights").get_json() if f["id"] == "F300")
        self.assertEqual(flight["state"], "Running")
        self.assertEqual(self.client.get("/api/statistics").get_json()["resource_requests_granted"], 2)

    def test_no_double_release(self):
        self.client.post("/api/flights/F101/request", json={"runways": 1, "gates": 1})
        self.assertEqual(self.client.post("/api/flights/F101/terminate").status_code, 200)
        self.assertEqual(self.client.post("/api/flights/F101/terminate").status_code, 400)
        self.assertEqual(self.client.get("/api/resources").get_json()["runways"]["available"], 2)

    def test_known_safe_and_unsafe_bankers_states(self):
        safe, sequence = simulator.check_safe_state()
        self.assertTrue(safe); self.assertEqual(set(sequence), {"F101", "F102"})
        with simulator.resource_lock:
            simulator.resources = {"runways": {"total": 2, "available": 0}, "gates": {"total": 2, "available": 0}}
            simulator.flights = [
                {"id": "A", "priority": 1, "state": "Running", "allocated": {"runways": 1, "gates": 0}, "maximum": {"runways": 1, "gates": 1}},
                {"id": "B", "priority": 1, "state": "Running", "allocated": {"runways": 0, "gates": 1}, "maximum": {"runways": 1, "gates": 1}},
            ]
        self.assertEqual(simulator.check_safe_state(), (False, []))

    def test_actual_deadlock_and_non_deadlocked_waiter(self):
        with simulator.resource_lock:
            simulator.resources = {"runways": {"total": 2, "available": 0}, "gates": {"total": 2, "available": 0}}
            simulator.flights = [
                {"id": "A", "priority": 1, "state": "Waiting", "allocated": {"runways": 1, "gates": 0}, "maximum": {"runways": 2, "gates": 1}},
                {"id": "B", "priority": 1, "state": "Waiting", "allocated": {"runways": 0, "gates": 1}, "maximum": {"runways": 1, "gates": 2}},
            ]
            simulator.pending_requests.update(A={"runways": 0, "gates": 1}, B={"runways": 1, "gates": 0})
        result = self.client.get("/api/deadlock-check").get_json()
        self.assertTrue(result["actual_deadlock_detected"])
        self.assertEqual(set(result["deadlocked_flights"]), {"A", "B"})
        with simulator.resource_lock:
            simulator.pending_requests.clear(); simulator.flights[1]["allocated"] = {"runways": 0, "gates": 0}
        self.assertFalse(self.client.get("/api/deadlock-check").get_json()["actual_deadlock_detected"])

    def test_activity_log_and_statistics_api(self):
        self.add("LOG")
        self.assertTrue(self.client.get("/api/activity-log").get_json()["events"])
        stats = self.client.get("/api/statistics").get_json()
        self.assertIn("runway_utilization", stats)
        self.assertIn("pending_requests", stats)


if __name__ == "__main__":
    unittest.main()
