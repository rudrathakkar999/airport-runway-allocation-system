// API endpoints
const API = {
flights: "/api/flights",
resources: "/api/resources",
status: "/api/status",
schedule: "/api/schedule",
deadlockCheck: "/api/deadlock-check" // NEW
};

// Existing elements
const flightForm = document.getElementById("flightForm");
const formMessage = document.getElementById("formMessage");
const schedulerMessage = document.getElementById("schedulerMessage");
const flightTableBody = document.getElementById("flightTableBody");
const refreshButton = document.getElementById("refreshButton");
const scheduleButton = document.getElementById("scheduleButton");

// NEW: Resource request elements
const resourceRequestForm = document.getElementById("resourceRequestForm");
const requestFlightId = document.getElementById("requestFlightId");
const resourceRequestMessage = document.getElementById("resourceRequestMessage");
const deadlockCheckButton = document.getElementById("deadlockCheckButton");
const deadlockResults = document.getElementById("deadlockResults");

// Fetch JSON from the Flask backend
async function fetchJSON(url, options = {}) {
const response = await fetch(url, options);
const data = await response.json();


// CHANGE: Handle both "error" and "message" responses.
if (!response.ok) {
    throw new Error(data.error || data.message || "Request failed.");
}

return data;


}

// Load flight statistics
async function loadStatus() {
const data = await fetchJSON(API.status);


document.getElementById("totalFlights").textContent = data.total ?? 0;
document.getElementById("readyFlights").textContent = data.ready ?? 0;
document.getElementById("waitingFlights").textContent = data.waiting ?? 0;
document.getElementById("runningFlights").textContent = data.running ?? 0;
document.getElementById("terminatedFlights").textContent = data.terminated ?? 0;


}

// Load runway and gate availability
async function loadResources() {
const data = await fetchJSON(API.resources);


const runways = data.runways;
const gates = data.gates;

document.getElementById("availableRunways").textContent = runways.available;
document.getElementById("totalRunways").textContent = runways.total;

document.getElementById("availableGates").textContent = gates.available;
document.getElementById("totalGates").textContent = gates.total;

// Update resource progress bars
document.getElementById("runwayProgress").style.width =
    `${runways.total ? (runways.available / runways.total) * 100 : 0}%`;

document.getElementById("gateProgress").style.width =
    `${gates.total ? (gates.available / gates.total) * 100 : 0}%`;


}

// NEW: Update the flight selection dropdown
async function loadRequestFlightOptions() {
if (!requestFlightId) return;


const flights = await fetchJSON(API.flights);
const currentSelection = requestFlightId.value;

requestFlightId.innerHTML = '<option value="">Select a flight</option>';

flights
    .filter(flight => flight.state !== "Terminated")
    .forEach(flight => {
        const option = document.createElement("option");

        option.value = flight.id;
        option.textContent =
            `${flight.id} — ${flight.state} (Priority ${flight.priority})`;

        requestFlightId.appendChild(option);
    });

// Preserve the selection when it is still valid.
if ([...requestFlightId.options].some(option => option.value === currentSelection)) {
    requestFlightId.value = currentSelection;
}


}

// Load and display flights
async function loadFlights() {
const data = await fetchJSON(API.flights);
const flights = Array.isArray(data) ? data : data.flights;


flightTableBody.innerHTML = "";

if (!flights || flights.length === 0) {
    flightTableBody.innerHTML =
        '<tr><td colspan="6">No flights available.</td></tr>';
    return;
}

flights.forEach((flight) => {
    const row = document.createElement("tr");

    const actionHTML = flight.state === "Terminated"
        ? "Completed"
        : `<button class="terminate-button" data-flight-id="${flight.id}">Terminate</button>`;

    const allocatedRunways = flight.allocated?.runways ?? 0;
    const allocatedGates = flight.allocated?.gates ?? 0;
    const maxRunways = flight.maximum?.runways ?? 0;
    const maxGates = flight.maximum?.gates ?? 0;

    row.innerHTML = `
        <td>${flight.id}</td>
        <td>${flight.priority}</td>
        <td><span class="status-badge">${flight.state}</span></td>
        <td>${allocatedRunways} / ${allocatedGates}</td>
        <td>${maxRunways} / ${maxGates}</td>
        <td>${actionHTML}</td>
    `;

    flightTableBody.appendChild(row);
});


}

// Refresh the complete dashboard
async function refreshDashboard() {
if (refreshButton) {
refreshButton.disabled = true;
}


try {
    await Promise.all([
        loadFlights(),
        loadResources(),
        loadStatus(),
        loadRequestFlightOptions() // NEW
    ]);
} catch (error) {
    console.error("Dashboard refresh failed:", error);

    if (formMessage) {
        formMessage.textContent = error.message;
    }
} finally {
    if (refreshButton) {
        refreshButton.disabled = false;
    }
}


}

// Add a new flight
if (flightForm) {
flightForm.addEventListener("submit", async (event) => {
event.preventDefault();


    const flight = {
        id: document.getElementById("flightId").value.trim(),
        priority: Number(document.getElementById("priority").value),
        max_runways: Number(document.getElementById("maxRunways").value),
        max_gates: Number(document.getElementById("maxGates").value)
    };

    try {
        const result = await fetchJSON(API.flights, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(flight)
        });

        formMessage.textContent =
            result.message || "Flight added successfully.";

        flightForm.reset();

        await refreshDashboard();
    } catch (error) {
        formMessage.textContent = error.message;
    }
});


}

// Run the priority scheduler
if (scheduleButton) {
scheduleButton.addEventListener("click", async () => {
scheduleButton.disabled = true;


    try {
        const result = await fetchJSON(API.schedule, {
            method: "POST"
        });

        const sequence = Array.isArray(result.safe_sequence)
            ? result.safe_sequence.join(" → ")
            : "Unavailable";

        schedulerMessage.textContent =
            `${result.message || "Scheduling completed."} ` +
            `Safe state: ${result.safe_state ? "YES" : "NO"}. ` +
            `Safe sequence: ${sequence}`;

        await refreshDashboard();
    } catch (error) {
        schedulerMessage.textContent = error.message;
    } finally {
        scheduleButton.disabled = false;
    }
});


}

// NEW: Submit a resource request from the dashboard
if (resourceRequestForm) {
resourceRequestForm.addEventListener("submit", async (event) => {
event.preventDefault();


    const flightId = requestFlightId.value;

    const runways = Number(
        document.getElementById("requestRunways").value
    );

    const gates = Number(
        document.getElementById("requestGates").value
    );

    if (!flightId) {
        resourceRequestMessage.textContent = "Please select a flight.";
        return;
    }

    if (
        !Number.isInteger(runways) ||
        !Number.isInteger(gates) ||
        runways < 0 ||
        gates < 0 ||
        (runways === 0 && gates === 0)
    ) {
        resourceRequestMessage.textContent =
            "Enter valid resource quantities and request at least one resource.";
        return;
    }

    resourceRequestForm.querySelector('button[type="submit"]').disabled = true;

    try {
        // Fetch directly so HTTP 202 and 409 responses can be displayed.
        const response = await fetch(
            `/api/flights/${encodeURIComponent(flightId)}/request`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    runways: runways,
                    gates: gates
                })
            }
        );

        const result = await response.json();

        if (response.status === 202 && result.pending) {
            resourceRequestMessage.textContent =
                `⏳ ${result.message} Flight ${flightId} is waiting.`;
        } else if (response.ok && result.granted) {
            resourceRequestMessage.textContent =
                `✅ ${result.message} Safe sequence: ` +
                `${(result.safe_sequence || []).join(" → ")}`;
        } else {
            resourceRequestMessage.textContent =
                `❌ ${result.error || result.message || "Request failed."}`;
        }

        await refreshDashboard();

        // Refresh deadlock information after a request.
        await checkDeadlock();
    } catch (error) {
        resourceRequestMessage.textContent =
            `Error: ${error.message}`;
    } finally {
        resourceRequestForm.querySelector('button[type="submit"]').disabled = false;
    }
});


}

// NEW: Check deadlock and display analysis results
async function checkDeadlock() {
if (!deadlockResults) return;


deadlockResults.textContent = "Checking system state...";

try {
    const result = await fetchJSON(API.deadlockCheck);

    // Build results safely using textContent.
    deadlockResults.innerHTML = "";

    const heading = document.createElement("h3");
    heading.textContent = result.message;
    deadlockResults.appendChild(heading);

    const safeState = document.createElement("p");
    safeState.textContent =
        `Safe state: ${result.safe_state ? "YES" : "NO"}`;
    deadlockResults.appendChild(safeState);

    const deadlockStatus = document.createElement("p");
    deadlockStatus.textContent =
        `Actual deadlock: ${
            result.actual_deadlock_detected ? "DETECTED" : "NOT DETECTED"
        }`;
    deadlockResults.appendChild(deadlockStatus);

    const sequence = document.createElement("p");
    sequence.textContent =
        `Safe sequence: ${
            result.safe_sequence?.length
                ? result.safe_sequence.join(" → ")
                : "None available"
        }`;
    deadlockResults.appendChild(sequence);

    const deadlocked = document.createElement("p");
    deadlocked.textContent =
        `Deadlocked flights: ${
            result.deadlocked_flights?.length
                ? result.deadlocked_flights.join(", ")
                : "None"
        }`;
    deadlockResults.appendChild(deadlocked);

    const pendingHeading = document.createElement("h4");
    pendingHeading.textContent = "Pending Resource Requests";
    deadlockResults.appendChild(pendingHeading);

    if (result.pending_requests?.length) {
        const list = document.createElement("ul");

        result.pending_requests.forEach(item => {
            const entry = document.createElement("li");

            entry.textContent =
                `${item.id}: ${item.request.runways} runway(s), ` +
                `${item.request.gates} gate(s)`;

            list.appendChild(entry);
        });

        deadlockResults.appendChild(list);
    } else {
        const noPending = document.createElement("p");
        noPending.textContent = "No pending requests.";
        deadlockResults.appendChild(noPending);
    }

    const detectionSequence = document.createElement("p");
    detectionSequence.textContent =
        `Detection completion sequence: ${
            result.detection_completion_sequence?.length
                ? result.detection_completion_sequence.join(" → ")
                : "None"
        }`;
    deadlockResults.appendChild(detectionSequence);

} catch (error) {
    deadlockResults.textContent =
        `Could not check deadlock: ${error.message}`;
}


}

// NEW: Deadlock check button
if (deadlockCheckButton) {
deadlockCheckButton.addEventListener("click", async () => {
deadlockCheckButton.disabled = true;


    try {
        await checkDeadlock();
    } finally {
        deadlockCheckButton.disabled = false;
    }
});


}

// Terminate a flight and release its resources
if (flightTableBody) {
flightTableBody.addEventListener("click", async (event) => {
const button = event.target.closest("[data-flight-id]");


    if (!button) {
        return;
    }

    const flightId = button.dataset.flightId;

    if (!confirm(`Terminate flight ${flightId}?`)) {
        return;
    }

    button.disabled = true;

    try {
        const result = await fetchJSON(
            `/api/flights/${encodeURIComponent(flightId)}/terminate`,
            { method: "POST" }
        );

        formMessage.textContent =
            result.message || "Flight terminated successfully.";

        await refreshDashboard();
        await checkDeadlock(); // NEW
    } catch (error) {
        formMessage.textContent = error.message;
        button.disabled = false;
    }
});


}

// Refresh button
if (refreshButton) {
refreshButton.addEventListener("click", async () => {
await refreshDashboard();
await checkDeadlock(); // NEW
});
}

// Load dashboard when the page opens
refreshDashboard();
