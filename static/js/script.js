// API endpoints
const API = {
    flights: "/api/flights",
    resources: "/api/resources",
    status: "/api/status",
    schedule: "/api/schedule"
};

const flightForm = document.getElementById("flightForm");
const formMessage = document.getElementById("formMessage");
const schedulerMessage = document.getElementById("schedulerMessage");
const flightTableBody = document.getElementById("flightTableBody");
const refreshButton = document.getElementById("refreshButton");
const scheduleButton = document.getElementById("scheduleButton");

// Fetch JSON from the Flask backend
async function fetchJSON(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();
    //FIX: FLASK may return errors under either "error" or "message"
    if (!response.ok) {
        throw new Error(data.message || "Request failed.");
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
        `${(runways.available / runways.total) * 100}%`;

    document.getElementById("gateProgress").style.width =
        `${(gates.available / gates.total) * 100}%`;
}

// Load and display flights
// FIX: Handle the API response as a direct array of flights
async function loadFlights() {
    const data = await fetchJSON(API.flights);

    // FIX: Your API returns an array directly, not data.flights
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

        // FIX: Read allocated and maximum resources from nested objects
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
            loadStatus()
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

            formMessage.textContent = result.message || "Flight added successfully.";
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
        } catch (error) {
            formMessage.textContent = error.message;
            button.disabled = false;
        }
    });
}

// Refresh button
if (refreshButton) {
    refreshButton.addEventListener("click", refreshDashboard);
}

// Load dashboard when the page opens
refreshDashboard();

