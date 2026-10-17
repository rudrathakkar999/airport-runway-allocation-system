# Airport Runway Resource Allocation System

An educational Flask dashboard that models flights as processes competing for runway and gate resources. It is an Operating Systems mini-project, not a real airport-control system.

## Features and OS concepts

- Process states: `Ready`, `Waiting`, `Running`, and `Terminated`.
- Non-preemptive priority scheduling; priority `1` is highest. A flight starts only when its complete remaining claim can be allocated safely.
- Runway and gate allocation, release on termination, and resource accounting protected by one `RLock`.
- Banker's Algorithm safety checks. `Need = Maximum - Allocation`; the safety simulation releases a simulated flight allocation only after its need can be met. Terminated flights are already finished.
- Resource requests are granted only if they fit both remaining need and availability and leave a safe state. Requests that merely lack available resources are queued, not rejected; queued requests are retried in priority order after a termination releases resources.
- Actual deadlock detection is separate from safety checking. Its `Work` vector starts with available resources, then it repeatedly lets an allocated flight finish when its outstanding queued request fits `Work`. Unfinished resource holders are deadlocked. An unsafe state is therefore not automatically a deadlock.
- Live statistics, bounded 100-entry execution log, dashboard refresh, and helpful JSON errors.

Request counters are in-memory: **granted** increments only when an allocation is actually committed (including a later queued grant); **rejected** increments for a submitted request rejected for an invalid flight/state/need or an unsafe allocation. A queued request increments neither counter.

## Structure

- `app.py` — Flask routes, simulator state, scheduling, Banker safety and deadlock algorithms.
- `templates/index.html` — dashboard.
- `static/js/script.js` — API integration and dashboard updates.
- `static/css/style.css` — dashboard styling.
- `test_app.py` — isolated `unittest` API/algorithm tests.

## Setup and run (Windows PowerShell)

```powershell
cd "D:\Projects\Airport Runway Allocation System"
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. If the virtual environment does not exist, create it first with `py -3.13 -m venv .venv`.

## Tests

```powershell
cd "D:\Projects\Airport Runway Allocation System"
.\.venv\Scripts\Activate.ps1
python -m unittest -v
```

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET / | Dashboard |
| GET, POST | `/api/flights` | List or create flights |
| POST | `/api/flights/<flight_id>/request` | Request runways/gates |
| POST | `/api/flights/<flight_id>/terminate` | Terminate and release resources |
| GET | `/api/resources` | Available and total resources |
| GET | `/api/status` | State counts |
| GET | `/api/statistics` | Counts, utilization, request counters |
| POST | `/api/schedule` | Run priority scheduler |
| GET | `/api/deadlock-check` | Safety and actual-deadlock analysis |
| GET | `/api/activity-log` | Most recent simulator events |

## Demonstration

1. Load the dashboard and inspect initial flights/resources.
2. Add flights with different priorities, then select **Run Scheduler**.
3. Request resources for a flight; inspect the safe sequence and statistics.
4. Queue a request by exhausting a resource, then terminate the holder to show automatic pending-request processing.
5. Select **Check Deadlock** and use the activity log to explain the decision.

## Limitations

All state is intentionally in memory and resets when the server restarts. Scheduling does not model elapsed flight time; users terminate a running flight to simulate completion. There are only two resource classes and no authentication or persistence.
