from flask import Flask, jsonify, render_template, request
from threading import Lock

app = Flask(__name__)

# Shared data protection using a mutex lock
resource_lock = Lock()

# Airport resources
resources = {
    "runways": {"total": 2, "available": 2},
    "gates": {"total": 3, "available": 3}
}

# Flight process information
flights = [
    {
        "id": "F101",
        "priority": 1,
        "state": "Ready",
        "allocated": {"runways": 0, "gates": 0},
        "maximum": {"runways": 1, "gates": 1}
    },
    {
        "id": "F102",
        "priority": 2,
        "state": "Waiting",
        "allocated": {"runways": 0, "gates": 0},
        "maximum": {"runways": 1, "gates": 1}
    }
]


# --------------------------------------------------
# BANKER'S ALGORITHM
# --------------------------------------------------

def check_safe_state(allocation, available):
    # FIX: Use the current allocation and available resources
    # to simulate whether every non-terminated flight can finish.

    count = len(flights)
    work = available.copy()
    finished = [
        flight["state"] == "Terminated"
        for flight in flights
    ]
    safe_sequence = []

    # FIX: Reject inconsistent allocation data.
    if len(allocation) != count:
        return False, []

    # FIX: Validate allocations and resource availability.
    for resource in ("runways", "gates"):
        if work[resource] < 0:
            return False, []

        for item in allocation:
            if item[resource] < 0:
                return False, []

    # FIX: Check that each allocation does not exceed its maximum.
    for i, flight in enumerate(flights):
        for resource in ("runways", "gates"):
            if allocation[i][resource] > flight["maximum"][resource]:
                return False, []

    # FIX: Standard Banker's safety-check loop.
    while True:
        found = False

        for i, flight in enumerate(flights):
            if finished[i]:
                continue

            # Remaining resources needed to finish this flight
            need_runways = (
                flight["maximum"]["runways"]
                - allocation[i]["runways"]
            )

            need_gates = (
                flight["maximum"]["gates"]
                - allocation[i]["gates"]
            )

            # Can this flight finish with the simulated resources?
            if (
                need_runways <= work["runways"]
                and need_gates <= work["gates"]
            ):
                # Simulate the flight finishing and releasing resources
                work["runways"] += allocation[i]["runways"]
                work["gates"] += allocation[i]["gates"]

                finished[i] = True
                safe_sequence.append(flight["id"])
                found = True

        # Stop if no remaining flight can finish.
        if not found:
            break

    # FIX: A state is safe only if every non-terminated flight can finish.
    if all(finished):
        return True, safe_sequence

    return False, []


def get_current_allocation():
    return [
        {
            "runways": flight["allocated"]["runways"],
            "gates": flight["allocated"]["gates"]
        }
        for flight in flights
    ]


def get_available_resources():
    return {
        "runways": resources["runways"]["available"],
        "gates": resources["gates"]["available"]
    }


# --------------------------------------------------
# PRIORITY SCHEDULING AND RESOURCE ALLOCATION
# --------------------------------------------------

def schedule_flights():
    with resource_lock:
        # Lower priority number means higher priority.
        candidates = sorted(
            [
                flight for flight in flights
                if flight["state"] in ("Ready", "Waiting")
            ],
            key=lambda flight: (flight["priority"], flight["id"])
        )

        for flight in candidates:
            need_runways = (
                flight["maximum"]["runways"]
                - flight["allocated"]["runways"]
            )

            need_gates = (
                flight["maximum"]["gates"]
                - flight["allocated"]["gates"]
            )

            # Check whether resources are currently available.
            if (
                need_runways > resources["runways"]["available"]
                or need_gates > resources["gates"]["available"]
            ):
                flight["state"] = "Waiting"
                continue

            allocation = get_current_allocation()
            available = get_available_resources()

            index = flights.index(flight)

            # Simulate the proposed allocation before committing it.
            allocation[index]["runways"] += need_runways
            allocation[index]["gates"] += need_gates

            available["runways"] -= need_runways
            available["gates"] -= need_gates

            # Allocate only if the resulting state is safe.
            safe, _ = check_safe_state(allocation, available)

            if safe:
                # Commit the allocation.
                flight["allocated"]["runways"] += need_runways
                flight["allocated"]["gates"] += need_gates

                resources["runways"]["available"] -= need_runways
                resources["gates"]["available"] -= need_gates

                flight["state"] = "Running"
            else:
                flight["state"] = "Waiting"


# --------------------------------------------------
# TERMINATE A FLIGHT
# --------------------------------------------------

def terminate_flight(flight_id):
    with resource_lock:
        flight = next(
            (item for item in flights if item["id"] == flight_id),
            None
        )

        if flight is None:
            return False, "Flight not found"

        if flight["state"] == "Terminated":
            return False, "Flight is already terminated"

        # Release all resources allocated to the flight.
        resources["runways"]["available"] += (
            flight["allocated"]["runways"]
        )

        resources["gates"]["available"] += (
            flight["allocated"]["gates"]
        )

        flight["allocated"] = {
            "runways": 0,
            "gates": 0
        }

        flight["state"] = "Terminated"

        return True, "Flight terminated successfully"


# --------------------------------------------------
# MAIN DASHBOARD
# --------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


# --------------------------------------------------
# FLIGHT API
# --------------------------------------------------

@app.route("/api/flights", methods=["GET"])
def get_flights():
    with resource_lock:
        # The frontend expects a direct array of flights.
        return jsonify(flights)


@app.route("/api/flights", methods=["POST"])
def add_flight():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required"}), 400

    flight_id = str(data.get("id", "")).strip()

    if not flight_id:
        return jsonify({"error": "Flight ID is required"}), 400

    try:
        priority = int(data.get("priority", 2))
        max_runways = int(data.get("max_runways", 1))
        max_gates = int(data.get("max_gates", 1))
    except (ValueError, TypeError):
        return jsonify({"error": "Values must be integers"}), 400

    if priority < 1 or max_runways < 0 or max_gates < 0:
        return jsonify({
            "error": "Invalid priority or resource values"
        }), 400

    if max_runways > resources["runways"]["total"]:
        return jsonify({
            "error": "Runway requirement exceeds capacity"
        }), 400

    if max_gates > resources["gates"]["total"]:
        return jsonify({
            "error": "Gate requirement exceeds capacity"
        }), 400

    with resource_lock:
        # Prevent duplicate flight IDs, including terminated flights.
        if any(item["id"] == flight_id for item in flights):
            return jsonify({"error": "Flight ID already exists"}), 409

        flight = {
            "id": flight_id,
            "priority": priority,
            "state": "Ready",
            "allocated": {"runways": 0, "gates": 0},
            "maximum": {
                "runways": max_runways,
                "gates": max_gates
            }
        }

        flights.append(flight)

    return jsonify({
        "message": "Flight added successfully",
        "flight": flight
    }), 201


# --------------------------------------------------
# RESOURCE API
# --------------------------------------------------

@app.route("/api/resources", methods=["GET"])
def get_resources():
    with resource_lock:
        return jsonify(resources)


# --------------------------------------------------
# FLIGHT STATUS API
# --------------------------------------------------

@app.route("/api/status", methods=["GET"])
def get_status():
    with resource_lock:
        # FIX: Return "total" because script.js uses data.total.
        total = len(flights)

        return jsonify({
            "total": total,
            "total_flights": total,
            "ready": sum(
                flight["state"] == "Ready" for flight in flights
            ),
            "waiting": sum(
                flight["state"] == "Waiting" for flight in flights
            ),
            "running": sum(
                flight["state"] == "Running" for flight in flights
            ),
            "terminated": sum(
                flight["state"] == "Terminated" for flight in flights
            )
        })


# --------------------------------------------------
# RUN SCHEDULER API
# --------------------------------------------------

@app.route("/api/schedule", methods=["POST"])
def run_scheduler():
    schedule_flights()

    with resource_lock:
        # Check the final resource-allocation state.
        safe, sequence = check_safe_state(
            get_current_allocation(),
            get_available_resources()
        )

        return jsonify({
            "message": "Scheduling completed",
            "safe_state": safe,
            "safe_sequence": sequence,
            "flights": flights,
            "resources": resources
        })


# --------------------------------------------------
# TERMINATE FLIGHT API
# --------------------------------------------------

@app.route("/api/flights/<flight_id>/terminate", methods=["POST"])
def complete_flight(flight_id):
    success, message = terminate_flight(flight_id)

    if not success:
        # FIX: Return an error key understood by the frontend.
        status_code = 404 if message == "Flight not found" else 400
        return jsonify({"error": message}), status_code

    return jsonify({"message": message})


# --------------------------------------------------
# START FLASK APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)