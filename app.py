"""Airport runway and gate allocation simulator."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
NAMES = ("runways", "gates")
resource_lock = RLock()
DEFAULT_RESOURCES = {"runways": {"total": 2, "available": 2}, "gates": {"total": 3, "available": 3}}
DEFAULT_FLIGHTS = [
    {"id": "F101", "priority": 1, "state": "Ready", "allocated": {"runways": 0, "gates": 0}, "maximum": {"runways": 1, "gates": 1}},
    {"id": "F102", "priority": 2, "state": "Waiting", "allocated": {"runways": 0, "gates": 0}, "maximum": {"runways": 1, "gates": 1}},
]
resources, flights = deepcopy(DEFAULT_RESOURCES), deepcopy(DEFAULT_FLIGHTS)
pending_requests, request_statistics = {}, {"granted": 0, "rejected": 0}
activity_log = deque(maxlen=100)

def log(message):
    activity_log.appendleft({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "message": message})

def available(): return {n: resources[n]["available"] for n in NAMES}
def allocations(): return [{n: f["allocated"][n] for n in NAMES} for f in flights]
def need(f): return {n: f["maximum"][n] - f["allocated"][n] for n in NAMES}
def fits(left, right): return all(left[n] <= right[n] for n in NAMES)
def vector(value): return isinstance(value, dict) and all(type(value.get(n)) is int and value[n] >= 0 for n in NAMES)
def find(flight_id): return next((f for f in flights if f["id"] == flight_id), None)

def check_safe_state(allocation=None, work=None, flight_list=None):
    """Banker's safety test; uses copies only and never mutates actual state."""
    flist = flights if flight_list is None else flight_list
    alloc = allocations() if allocation is None else allocation
    work = available() if work is None else work.copy()
    if len(alloc) != len(flist) or not vector(work) or any(not vector(a) for a in alloc): return False, []
    finished, sequence = [f["state"] == "Terminated" for f in flist], []
    for i, f in enumerate(flist):
        if not vector(f.get("maximum")) or any(alloc[i][n] > f["maximum"][n] for n in NAMES): return False, []
    changed = True
    while changed:
        changed = False
        for i, f in enumerate(flist):
            if not finished[i] and fits({n: f["maximum"][n] - alloc[i][n] for n in NAMES}, work):
                for n in NAMES: work[n] += alloc[i][n]
                finished[i], changed = True, True
                sequence.append(f["id"])
    return (True, sequence) if all(finished) else (False, [])

def commit(flight, request_vector):
    for n in NAMES:
        flight["allocated"][n] += request_vector[n]
        resources[n]["available"] -= request_vector[n]
    flight["state"] = "Running"

def try_grant(flight, request_vector):
    work = available()
    if not fits(request_vector, work): return False, []
    alloc, index = allocations(), flights.index(flight)
    for n in NAMES: alloc[index][n], work[n] = alloc[index][n] + request_vector[n], work[n] - request_vector[n]
    safe, sequence = check_safe_state(alloc, work)
    if safe: commit(flight, request_vector)
    return safe, sequence

def process_pending_requests():
    """Caller holds lock. Each queued request is granted and counted at most once."""
    candidates = sorted((f for f in flights if f["id"] in pending_requests and f["state"] != "Terminated"), key=lambda f: (f["priority"], f["id"]))
    for f in candidates:
        request_vector = pending_requests[f["id"]]
        if not fits(request_vector, need(f)):
            pending_requests.pop(f["id"]); request_statistics["rejected"] += 1
            log(f"Pending request for {f['id']} rejected: exceeds remaining need.")
        else:
            granted, _ = try_grant(f, request_vector)
            if granted:
                pending_requests.pop(f["id"]); request_statistics["granted"] += 1
                log(f"Pending request for {f['id']} granted; flight is Running.")

def schedule_flights():
    with resource_lock:
        started = []
        for f in sorted((x for x in flights if x["state"] in ("Ready", "Waiting") and x["id"] not in pending_requests), key=lambda x: (x["priority"], x["id"])):
            request_vector = need(f)
            if not any(request_vector.values()): f["state"] = "Running"; started.append(f["id"]); continue
            granted, _ = try_grant(f, request_vector)
            if granted: started.append(f["id"]); log(f"Scheduler started {f['id']} (priority {f['priority']}).")
            else: f["state"] = "Waiting"
        log("Scheduler ran" + (f"; started {', '.join(started)}." if started else "; no eligible flight could start."))

def statistics():
    out = {"total_flights": len(flights), "ready_flights": 0, "waiting_flights": 0, "running_flights": 0, "completed_flights": 0}
    mapping = {"Ready": "ready_flights", "Waiting": "waiting_flights", "Running": "running_flights", "Terminated": "completed_flights"}
    for f in flights: out[mapping[f["state"]]] += 1
    for plural, singular in (("runways", "runway"), ("gates", "gate")):
        total, free = resources[plural]["total"], resources[plural]["available"]
        out[f"total_{plural}"], out[f"available_{plural}"] = total, free
        out[f"{singular}_utilization"] = round((total - free) * 100 / total, 1) if total else 0.0
    out.update({"resource_requests_granted": request_statistics["granted"], "resource_requests_rejected": request_statistics["rejected"], "pending_requests": len(pending_requests)})
    return out

def detect_deadlock():
    """Detection differs from safety: only holders with outstanding requests are considered."""
    work, holders, sequence = available(), {f["id"]: f for f in flights if f["state"] != "Terminated" and any(f["allocated"].values())}, []
    changed = True
    while changed:
        changed = False
        for fid, f in list(holders.items()):
            if fits(pending_requests.get(fid, {"runways": 0, "gates": 0}), work):
                for n in NAMES: work[n] += f["allocated"][n]
                del holders[fid]; sequence.append(fid); changed = True
    return list(holders), sequence

@app.errorhandler(404)
def missing(_): return jsonify({"error": "Endpoint not found"}), 404
@app.route("/")
def home(): return render_template("index.html")

@app.route("/api/flights", methods=["GET"])
def get_flights():
    with resource_lock: return jsonify(deepcopy(flights))

@app.route("/api/flights", methods=["POST"])
def add_flight():
    data = request.get_json(silent=True)
    if not isinstance(data, dict): return jsonify({"error": "A JSON object is required"}), 400
    fid, values = str(data.get("id", "")).strip(), [data.get("priority", 2), data.get("max_runways", 1), data.get("max_gates", 1)]
    if not fid or any(type(v) is not int for v in values): return jsonify({"error": "Flight ID is required and numeric values must be integers"}), 400
    priority, runways, gates = values
    if priority < 1 or runways < 0 or gates < 0: return jsonify({"error": "Priority must be at least 1 and resource values cannot be negative"}), 400
    with resource_lock:
        if runways > resources["runways"]["total"] or gates > resources["gates"]["total"]: return jsonify({"error": "Maximum resource requirement exceeds system capacity"}), 400
        if find(fid): return jsonify({"error": "Flight ID already exists"}), 409
        f = {"id": fid, "priority": priority, "state": "Ready", "allocated": {"runways": 0, "gates": 0}, "maximum": {"runways": runways, "gates": gates}}
        flights.append(f); log(f"Flight {fid} created with priority {priority}.")
        return jsonify({"message": "Flight added successfully", "flight": f}), 201

@app.route("/api/flights/<flight_id>/request", methods=["POST"])
def request_resources_api(flight_id):
    data = request.get_json(silent=True)
    if not vector(data): return jsonify({"error": "runways and gates must be non-negative integers"}), 400
    req = {n: data[n] for n in NAMES}
    if not any(req.values()): return jsonify({"error": "Request at least one resource"}), 400
    with resource_lock:
        f = find(flight_id)
        if not f: request_statistics["rejected"] += 1; return jsonify({"error": "Flight not found"}), 404
        if f["state"] == "Terminated" or flight_id in pending_requests or not fits(req, need(f)):
            request_statistics["rejected"] += 1
            msg = "Terminated flights cannot request resources" if f["state"] == "Terminated" else "This flight already has a pending request" if flight_id in pending_requests else "Request exceeds the flight's remaining need"
            log(f"Request for {flight_id} rejected: {msg}."); return jsonify({"error": msg}), 409 if flight_id in pending_requests else 400
        log(f"Flight {flight_id} requested {req['runways']} runway(s) and {req['gates']} gate(s).")
        if not fits(req, available()):
            pending_requests[flight_id] = req; f["state"] = "Waiting"; log(f"Request for {flight_id} queued because resources are unavailable.")
            return jsonify({"message": "Request queued: insufficient resources", "granted": False, "pending": True, "requested": req}), 202
        granted, sequence = try_grant(f, req)
        if not granted:
            request_statistics["rejected"] += 1; log(f"Request for {flight_id} rejected because it would be unsafe.")
            return jsonify({"message": "Request denied: unsafe system state", "granted": False, "pending": False, "safe_state": False}), 409
        request_statistics["granted"] += 1; log(f"Request for {flight_id} granted; flight is Running.")
        return jsonify({"message": "Resources granted successfully", "granted": True, "pending": False, "safe_state": True, "safe_sequence": sequence, "flight": f, "resources": resources})

@app.route("/api/resources")
def get_resources_api():
    with resource_lock: return jsonify(deepcopy(resources))
@app.route("/api/status")
def get_status():
    with resource_lock:
        s = statistics(); return jsonify({"total": s["total_flights"], "total_flights": s["total_flights"], "ready": s["ready_flights"], "waiting": s["waiting_flights"], "running": s["running_flights"], "terminated": s["completed_flights"]})
@app.route("/api/statistics")
def get_statistics():
    with resource_lock: return jsonify(statistics())
@app.route("/api/schedule", methods=["POST"])
def run_scheduler():
    schedule_flights()
    with resource_lock:
        safe, sequence = check_safe_state(); return jsonify({"message": "Scheduling completed", "safe_state": safe, "safe_sequence": sequence, "flights": deepcopy(flights), "resources": deepcopy(resources)})
@app.route("/api/flights/<flight_id>/terminate", methods=["POST"])
def complete_flight(flight_id):
    with resource_lock:
        f = find(flight_id)
        if not f: return jsonify({"error": "Flight not found"}), 404
        if f["state"] == "Terminated": return jsonify({"error": "Flight is already terminated"}), 400
        released = f["allocated"].copy()
        for n in NAMES: resources[n]["available"] += f["allocated"][n]; f["allocated"][n] = 0
        pending_requests.pop(flight_id, None); f["state"] = "Terminated"
        log(f"Flight {flight_id} terminated and released {released['runways']} runway(s), {released['gates']} gate(s).")
        process_pending_requests(); return jsonify({"message": "Flight terminated successfully"})
@app.route("/api/deadlock-check")
def deadlock_check():
    with resource_lock:
        deadlocked, completion = detect_deadlock(); safe, sequence = check_safe_state(); actual = bool(deadlocked)
        message = "Deadlock detected: some flights cannot proceed." if actual else "Unsafe state detected, but no actual deadlock was found." if not safe else "No deadlock detected."
        log(f"Deadlock check: {'deadlock in ' + ', '.join(deadlocked) if actual else 'no actual deadlock'}.")
        return jsonify({"safe_state": safe, "safe_sequence": sequence, "actual_deadlock_detected": actual, "deadlocked_flights": deadlocked, "pending_requests": [{"id": k, "request": v} for k, v in pending_requests.items()], "detection_completion_sequence": completion, "message": message})
@app.route("/api/activity-log")
def get_activity_log():
    with resource_lock: return jsonify({"events": list(activity_log)})
if __name__ == "__main__": app.run(debug=True)
