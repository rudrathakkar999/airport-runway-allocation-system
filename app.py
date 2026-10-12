from flask import Flask, jsonify, render_template, request
from threading import Lock

app = Flask(__name__)

# --------------------------------------------------
# SHARED STATE AND MUTEX
# --------------------------------------------------

resource_lock = Lock()

resources = {
    "runways": {"total": 2, "available": 2},
    "gates": {"total": 3, "available": 3}
}

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

# NEW: Store outstanding resource requests by flight ID.
# Example: {"F103": {"runways": 1, "gates": 1}}
pending_requests = {}


# --------------------------------------------------
# RESOURCE HELPER FUNCTIONS
# --------------------------------------------------

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


def request_fits_available(requested, available):
    return (
        requested["runways"] <= available["runways"]
        and requested["gates"] <= available["gates"]
    )


def request_fits_need(flight, requested):
    remaining_runways = (
        flight["maximum"]["runways"]
        - flight["allocated"]["runways"]
    )

    remaining_gates = (
        flight["maximum"]["gates"]
        - flight["allocated"]["gates"]
    )

    return (
        requested["runways"] <= remaining_runways
        and requested["gates"] <= remaining_gates
    )


# --------------------------------------------------
# BANKER'S ALGORITHM: SAFETY CHECK
# --------------------------------------------------

def check_safe_state(allocation, available):
    count = len(flights)

    if len(allocation) != count:
        return False, []

    work = available.copy()

    # Terminated flights have already finished.
    finished = [
        flight["state"] == "Terminated"
        for flight in flights
    ]

    # Validate resource values and allocations.
    for resource in ("runways", "gates"):
        if work[resource] < 0:
            return False, []

        for item in allocation:
            if item[resource] < 0:
                return False, []

    for i, flight in enumerate(flights):
        for resource in ("runways", "gates"):
            if allocation[i][resource] > flight["maximum"][resource]:
                return False, []

    safe_sequence = []

    while True:
        found = False

        for i, flight in enumerate(flights):
            if finished[i]:
                continue

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
                # Simulate completion and resource release.
                work["runways"] += allocation[i]["runways"]
                work["gates"] += allocation[i]["gates"]

                finished[i] = True
                safe_sequence.append(flight["id"])
                found = True

        if not found:
            break

    if all(finished):
        return True, safe_sequence

    return False, []


# --------------------------------------------------
# NEW: SAFELY GRANT PENDING RESOURCE REQUESTS
# --------------------------------------------------

def process_pending_requests():
    """
    Reconsider pending requests after resources are released.
    Must be called while resource_lock is held.
    """

    ordered_flights = sorted(
        [
            flight for flight in flights
            if flight["id"] in pending_requests
            and flight["state"] != "Terminated"
        ],
        key=lambda flight: (flight["priority"], flight["id"])
    )

    for flight in ordered_flights:
        flight_id = flight["id"]
        requested = pending_requests[flight_id]

        # CHANGE: Recalculate available resources after each allocation.
        available = get_available_resources()

        if not request_fits_available(requested, available):
            continue

        allocation = get_current_allocation()
        index = flights.index(flight)

        # CHANGE: Check whether the request exceeds the flight's remaining need.
        if not request_fits_need(flight, requested):
            del pending_requests[flight_id]
            continue

        allocation[index]["runways"] += requested["runways"]
        allocation[index]["gates"] += requested["gates"]

        simulated_available = available.copy()
        simulated_available["runways"] -= requested["runways"]
        simulated_available["gates"] -= requested["gates"]

        safe, _ = check_safe_state(allocation, simulated_available)

        if not safe:
            continue

        # Commit the allocation.
        flight["allocated"]["runways"] += requested["runways"]
        flight["allocated"]["gates"] += requested["gates"]

        resources["runways"]["available"] -= requested["runways"]
        resources["gates"]["available"] -= requested["gates"]

        flight["state"] = "Running"

        del pending_requests[flight_id]

# --------------------------------------------------
# PRIORITY SCHEDULING AND RESOURCE ALLOCATION
# --------------------------------------------------

def schedule_flights():
    with resource_lock:
        candidates = sorted(
            [
                flight for flight in flights
                if flight["state"] in ("Ready", "Waiting")
                and flight["id"] not in pending_requests
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

            if (
                need_runways > resources["runways"]["available"]
                or need_gates > resources["gates"]["available"]
            ):
                flight["state"] = "Waiting"
                continue

            allocation = get_current_allocation()
            available = get_available_resources()
            index = flights.index(flight)

            # Simulate the proposed allocation.
            allocation[index]["runways"] += need_runways
            allocation[index]["gates"] += need_gates

            available["runways"] -= need_runways
            available["gates"] -= need_gates

            safe, _ = check_safe_state(allocation, available)

            if safe:
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

        # A terminated flight no longer has an outstanding request.
        pending_requests.pop(flight_id, None)

        # Release all resources held by this flight.
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

        # NEW: Try to grant other flights' pending requests.
        process_pending_requests()

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
        # Reject Boolean values and non-integer numeric values.
        raw_values = [
            data.get("priority", 2),
            data.get("max_runways", 1),
            data.get("max_gates", 1)
        ]

        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            for value in raw_values
        ):
            raise ValueError

        priority, max_runways, max_gates = raw_values

    except (ValueError, TypeError):
        return jsonify({"error": "Values must be integers"}), 400

    if priority < 1 or max_runways < 0 or max_gates < 0:
        return jsonify({
            "error": "Invalid priority or resource values"
        }), 400

    with resource_lock:
        if max_runways > resources["runways"]["total"]:
            return jsonify({
                "error": "Runway requirement exceeds capacity"
            }), 400

        if max_gates > resources["gates"]["total"]:
            return jsonify({
                "error": "Gate requirement exceeds capacity"
            }), 400

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
# NEW: DYNAMIC RESOURCE REQUEST API
# --------------------------------------------------

@app.route("/api/flights/<flight_id>/request", methods=["POST"])
def request_resources_api(flight_id):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required"}), 400

    requested_runways = data.get("runways", 0)
    requested_gates = data.get("gates", 0)

    # Only non-negative integers are valid.
    if (
        type(requested_runways) is not int
        or type(requested_gates) is not int
        or requested_runways < 0
        or requested_gates < 0
    ):
        return jsonify({
            "error": "Resource requests must be non-negative integers"
        }), 400

    if requested_runways == 0 and requested_gates == 0:
        return jsonify({
            "error": "Request at least one resource"
        }), 400

    requested = {
        "runways": requested_runways,
        "gates": requested_gates
    }

    with resource_lock:
        flight = next(
            (item for item in flights if item["id"] == flight_id),
            None
        )

        if flight is None:
            return jsonify({"error": "Flight not found"}), 404

        if flight["state"] == "Terminated":
            return jsonify({
                "error": "Terminated flights cannot request resources"
            }), 400

        if flight_id in pending_requests:
            return jsonify({
                "error": "This flight already has a pending request"
            }), 409

        if not request_fits_need(flight, requested):
            return jsonify({
                "error": "Request exceeds the flight's remaining need"
            }), 400

        available = get_available_resources()

        # NEW: Keep unavailable requests pending rather than discarding them.
        if not request_fits_available(requested, available):
            pending_requests[flight_id] = requested
            flight["state"] = "Waiting"

            return jsonify({
                "message": "Request queued: insufficient resources",
                "granted": False,
                "pending": True,
                "requested": requested
            }), 202

        # Simulate the request before committing it.
        allocation = get_current_allocation()
        simulated_available = available.copy()
        index = flights.index(flight)

        allocation[index]["runways"] += requested_runways
        allocation[index]["gates"] += requested_gates

        simulated_available["runways"] -= requested_runways
        simulated_available["gates"] -= requested_gates

        safe, sequence = check_safe_state(
            allocation,
            simulated_available
        )

        if not safe:
            return jsonify({
                "message": "Request denied: unsafe system state",
                "granted": False,
                "pending": False,
                "safe_state": False
            }), 409

        # Commit the safe allocation.
        flight["allocated"]["runways"] += requested_runways
        flight["allocated"]["gates"] += requested_gates

        resources["runways"]["available"] -= requested_runways
        resources["gates"]["available"] -= requested_gates

        flight["state"] = "Running"

        return jsonify({
            "message": "Resources granted successfully",
            "granted": True,
            "pending": False,
            "safe_state": True,
            "safe_sequence": sequence,
            "flight": flight,
            "resources": resources
        }), 200


# --------------------------------------------------
# RESOURCE API
# --------------------------------------------------

@app.route("/api/resources", methods=["GET"])
def get_resources_api():
    with resource_lock:
        return jsonify(resources)


# --------------------------------------------------
# FLIGHT STATUS API
# --------------------------------------------------

@app.route("/api/status", methods=["GET"])
def get_status():
    with resource_lock:
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
        status_code = 404 if message == "Flight not found" else 400
        return jsonify({"error": message}), status_code

    return jsonify({"message": message})


# --------------------------------------------------
# NEW: GENUINE DEADLOCK DETECTION API
# --------------------------------------------------

@app.route("/api/deadlock-check", methods=["GET"])
def deadlock_check():
    with resource_lock:
        # Work represents resources currently available to the system.
        work = get_available_resources()

        # A flight with no allocated resources cannot be part of
        # a resource deadlock under the standard detection algorithm.
        finish = {}

        for flight in flights:
            allocation = flight["allocated"]

            finish[flight["id"]] = (
                flight["state"] == "Terminated"
                or (
                    allocation["runways"] == 0
                    and allocation["gates"] == 0
                )
            )

        completion_sequence = []

        # Repeatedly find an unfinished flight whose outstanding
        # request can be satisfied with the resources in Work.
        while True:
            found = False

            for flight in flights:
                flight_id = flight["id"]

                if finish[flight_id]:
                    continue

                # No outstanding request means the flight can finish
                # and release its currently allocated resources.
                outstanding = pending_requests.get(
                    flight_id,
                    {"runways": 0, "gates": 0}
                )

                if request_fits_available(outstanding, work):
                    work["runways"] += flight["allocated"]["runways"]
                    work["gates"] += flight["allocated"]["gates"]

                    finish[flight_id] = True
                    completion_sequence.append(flight_id)
                    found = True

            if not found:
                break

        # Remaining unfinished flights holding resources are deadlocked.
        deadlocked_flights = [
            flight["id"]
            for flight in flights
            if (
                not finish[flight["id"]]
                and flight["state"] != "Terminated"
            )
        ]

        # Report pending requests separately.
        outstanding_requests = [
            {
                "id": flight_id,
                "request": requested
            }
            for flight_id, requested in pending_requests.items()
        ]

        # Safety analysis is different from actual deadlock detection.
        safe, safe_sequence = check_safe_state(
            get_current_allocation(),
            get_available_resources()
        )

        actual_deadlock = len(deadlocked_flights) > 0

        if actual_deadlock:
            message = "Deadlock detected: some flights cannot proceed."
        elif not safe:
            message = (
                "Unsafe state detected, but no actual deadlock "
                "was found by the detection algorithm."
            )
        else:
            message = "No deadlock detected."

        return jsonify({
            "safe_state": safe,
            "safe_sequence": safe_sequence,
            "actual_deadlock_detected": actual_deadlock,
            "deadlocked_flights": deadlocked_flights,
            "pending_requests": outstanding_requests,
            "detection_completion_sequence": completion_sequence,
            "message": message
        })



# --------------------------------------------------
# START FLASK APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)