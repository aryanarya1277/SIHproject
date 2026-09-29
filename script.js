const eventStyles = {
    Rain: { type: "rain", icon: "fa-cloud-rain" },
    Flood: { type: "flood", icon: "fa-water" },
    Heatwave: { type: "heat", icon: "fa-sun" },
    Thunderstorm: { type: "thunder", icon: "fa-bolt" },
    Fog: { type: "fog", icon: "fa-smog" },
    "Dust Storm": { type: "dust", icon: "fa-wind" }
};

const indiaCityCoordinates = {
    Delhi: { latitude: 28.6139, longitude: 77.2090 },
    Mumbai: { latitude: 19.0760, longitude: 72.8777 },
    Kolkata: { latitude: 22.5726, longitude: 88.3639 },
    Chennai: { latitude: 13.0827, longitude: 80.2707 },
    Bengaluru: { latitude: 12.9716, longitude: 77.5946 },
    Guwahati: { latitude: 26.1445, longitude: 91.7362 },
    Jaipur: { latitude: 26.9124, longitude: 75.7873 },
    Patna: { latitude: 25.5941, longitude: 85.1376 }
};

const mapLocations = {
    india: [
        { name: "Delhi", country: "India", latitude: 28.6139, longitude: 77.2090 },
        { name: "Mumbai", country: "India", latitude: 19.0760, longitude: 72.8777 },
        { name: "Kolkata", country: "India", latitude: 22.5726, longitude: 88.3639 },
        { name: "Chennai", country: "India", latitude: 13.0827, longitude: 80.2707 },
        { name: "Bengaluru", country: "India", latitude: 12.9716, longitude: 77.5946 },
        { name: "Hyderabad", country: "India", latitude: 17.3850, longitude: 78.4867 },
        { name: "Ahmedabad", country: "India", latitude: 23.0225, longitude: 72.5714 },
        { name: "Jaipur", country: "India", latitude: 26.9124, longitude: 75.7873 },
        { name: "Lucknow", country: "India", latitude: 26.8467, longitude: 80.9462 },
        { name: "Patna", country: "India", latitude: 25.5941, longitude: 85.1376 },
        { name: "Guwahati", country: "India", latitude: 26.1445, longitude: 91.7362 },
        { name: "Srinagar", country: "India", latitude: 34.0837, longitude: 74.7973 },
        { name: "Bhopal", country: "India", latitude: 23.2599, longitude: 77.4126 },
        { name: "Thiruvananthapuram", country: "India", latitude: 8.5241, longitude: 76.9366 },
        { name: "Bhubaneswar", country: "India", latitude: 20.2961, longitude: 85.8245 }
    ],
    world: [
        { name: "New York", country: "United States", latitude: 40.7128, longitude: -74.0060 },
        { name: "Los Angeles", country: "United States", latitude: 34.0522, longitude: -118.2437 },
        { name: "Mexico City", country: "Mexico", latitude: 19.4326, longitude: -99.1332 },
        { name: "São Paulo", country: "Brazil", latitude: -23.5505, longitude: -46.6333 },
        { name: "London", country: "United Kingdom", latitude: 51.5072, longitude: -0.1276 },
        { name: "Paris", country: "France", latitude: 48.8566, longitude: 2.3522 },
        { name: "Moscow", country: "Russia", latitude: 55.7558, longitude: 37.6173 },
        { name: "Istanbul", country: "Türkiye", latitude: 41.0082, longitude: 28.9784 },
        { name: "Cairo", country: "Egypt", latitude: 30.0444, longitude: 31.2357 },
        { name: "Lagos", country: "Nigeria", latitude: 6.5244, longitude: 3.3792 },
        { name: "Nairobi", country: "Kenya", latitude: -1.2921, longitude: 36.8219 },
        { name: "Cape Town", country: "South Africa", latitude: -33.9249, longitude: 18.4241 },
        { name: "Dubai", country: "United Arab Emirates", latitude: 25.2048, longitude: 55.2708 },
        { name: "Riyadh", country: "Saudi Arabia", latitude: 24.7136, longitude: 46.6753 },
        { name: "Tehran", country: "Iran", latitude: 35.6892, longitude: 51.3890 },
        { name: "Beijing", country: "China", latitude: 39.9042, longitude: 116.4074 },
        { name: "Shanghai", country: "China", latitude: 31.2304, longitude: 121.4737 },
        { name: "Tokyo", country: "Japan", latitude: 35.6762, longitude: 139.6503 },
        { name: "Seoul", country: "South Korea", latitude: 37.5665, longitude: 126.9780 },
        { name: "Bangkok", country: "Thailand", latitude: 13.7563, longitude: 100.5018 },
        { name: "Singapore", country: "Singapore", latitude: 1.3521, longitude: 103.8198 },
        { name: "Jakarta", country: "Indonesia", latitude: -6.2088, longitude: 106.8456 },
        { name: "Sydney", country: "Australia", latitude: -33.8688, longitude: 151.2093 },
        { name: "Auckland", country: "New Zealand", latitude: -36.8509, longitude: 174.7645 }
    ]
};

const API_BASE_URL = window.location.port === "5500"
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : (window.API_BASE_URL || "");

const mapElement = document.querySelector("#map");
const eventsList = document.querySelector(".events-list");
const map = window.L && mapElement
    ? window.L.map(mapElement).setView([22.5, 78.9], 5)
    : null;
const markers = map ? window.L.featureGroup().addTo(map) : null;
const weatherMarkers = map ? window.L.featureGroup().addTo(map) : null;
const earthquakeMarkers = map ? window.L.featureGroup().addTo(map) : null;
const placeMarkers = map ? window.L.featureGroup().addTo(map) : null;
let mapHasInitialFit = false;
let eventsLoadVersion = 0;
let openMeteoClientRetryUntil = 0;
const eventLocationDataCache = new Map();
const eventLocationDataRequests = new Map();
const EVENT_LOCATION_DATA_TTL_MS = 15 * 60 * 1000;

if (map) {
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);
} else if (mapElement) {
    mapElement.textContent = "Map could not load because the map library is unavailable.";
}

async function requestJson(url, options = {}) {
    const requestOptions = { ...options };
    if (requestOptions.body !== undefined) {
        const headers = new Headers(requestOptions.headers);
        if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
        requestOptions.headers = headers;
    }
    const response = await fetch(`${API_BASE_URL}${url}`, requestOptions);
    let data;
    try {
        data = await response.json();
    } catch (error) {
        if (response.ok) throw error;
        throw new Error(`Request failed (${response.status}); server returned no JSON error details.`);
    }
    if (!response.ok) {
        const detail = data.detail;
        if (
            response.status === 429 &&
            typeof detail === "string" &&
            detail.includes("Open-Meteo") &&
            !url.includes("force_refresh=1")
        ) {
            const retryAfter = Number(response.headers.get("Retry-After"));
            openMeteoClientRetryUntil = Date.now() +
                (Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : 15 * 60) * 1000;
        }
        if (typeof detail === "string") {
            throw new Error(detail);
        }
        if (detail && typeof detail === "object") {
            const message = typeof detail.message === "string"
                ? detail.message
                : `Request failed (${response.status})`;
            const errors = Array.isArray(detail.errors)
                ? detail.errors.map((item) => {
                    const city = typeof item.city === "string" ? `${item.city}: ` : "";
                    return `${city}${item.detail || "unavailable"}`;
                }).join("; ")
                : "";
            throw new Error(errors ? `${message} ${errors}` : message);
        }
        throw new Error(`Request failed (${response.status})`);
    }
    return data;
}

function formatTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
        ? "Time unavailable"
        : new Intl.DateTimeFormat(undefined, {
            hour: "2-digit",
            minute: "2-digit",
            day: "2-digit",
            month: "short"
        }).format(date);
}

function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

function renderEvent(event) {
    const style = eventStyles[event.event] || { type: "rain", icon: "fa-cloud" };
    const item = makeElement("article", "event-item");
    const icon = makeElement("div", `event-icon ${style.type}`);
    const iconElement = makeElement("i");
    iconElement.className = `fa-solid ${style.icon}`;
    icon.append(iconElement);

    const info = makeElement("div", "event-info");
    info.append(
        makeElement("h3", "", event.location),
        makeElement("p", "", event.event)
    );
    if (event.is_demo) {
        info.append(makeElement("small", "demo-label", "Sample data"));
    }
    if (event.ai_classification) {
        const prediction = event.ai_classification;
        info.append(makeElement(
            "small",
            "ai-label",
            `AI text signal: ${prediction.disaster_label} (score ${Math.round(prediction.disaster_score * 100)}%); ` +
                `${prediction.social_event_type} (score ${Math.round(prediction.event_type_score * 100)}%). Not verification.`
        ));
    } else if (event.ai_classification_status === "model_unavailable") {
        info.append(makeElement("small", "ai-unavailable", "AI model unavailable; classification not provided."));
    }

    const time = makeElement("span", "event-time", formatTime(event.time));
    const statusClass = event.status === "Verified" ? "verified"
        : event.status === "Suspicious" ? "suspicious" : "review";
    const reportStatus = makeElement("span", `event-status ${statusClass}`, event.status);
    item.append(icon, info, time, reportStatus);
    const hasCoordinates = Number.isFinite(event.latitude) && Number.isFinite(event.longitude);
    const locationData = makeElement(
        "div",
        "event-location-data",
        hasCoordinates
            ? "Loading current location data from Open-Meteo and USGS…"
            : "Live location data unavailable: this report has no latitude/longitude."
    );
    item.append(locationData);
    return item;
}

function makePopup(event) {
    const popup = makeElement("div", "map-popup");
    popup.append(
        makeElement("strong", "", event.location),
        makeElement("p", "", `${event.event} · ${event.status}`),
        makeElement(
            "p",
            "",
            event.confidence === null
                ? "Confidence unavailable"
                : `Confidence: ${event.confidence}%`
        )
    );
    if (event.is_demo) popup.append(makeElement("small", "", "Sample data"));
    return popup;
}

function renderEvents(events) {
    eventsList.replaceChildren();
    const eventCards = [];
    if (!events.length) {
        eventsList.append(makeElement("p", "empty-message", "No reports match these filters."));
    } else {
        events.forEach((event) => {
            const card = renderEvent(event);
            eventCards.push(card);
            eventsList.append(card);
        });
    }

    if (markers) {
        markers.clearLayers();
        events.forEach((event) => {
            if (!Number.isFinite(event.latitude) || !Number.isFinite(event.longitude)) return;
            window.L.marker([event.latitude, event.longitude])
                .bindPopup(makePopup(event))
                .addTo(markers);
        });
    }
    return eventCards;
}

function fitMapToSources() {
    if (!map || mapHasInitialFit) return;
    const allMarkers = window.L.featureGroup([markers, weatherMarkers, earthquakeMarkers, placeMarkers]);
    if (!allMarkers.getLayers().length) return;
    map.fitBounds(allMarkers.getBounds().pad(0.15), { maxZoom: 6 });
    mapHasInitialFit = true;
}

function displayValue(value, unit = "") {
    return Number.isFinite(value) ? `${value}${unit}` : "Unavailable";
}

function weatherCacheLabel(weather) {
    if (weather.cache_status === "stale") {
        const nearbyPoint = Number.isFinite(weather.cache_location_distance_km)
            ? ` · nearby grid point ${weather.cache_location_distance_km} km away`
            : "";
        return ` · stale cached reading${nearbyPoint}`;
    }
    return weather.cache_status === "cached" ? " · cached reading" : "";
}

function weatherSourceLabel(weather) {
    return weather.source || "Open-Meteo";
}

function makeWeatherPopup(weather) {
    const popup = makeElement("div", "map-popup");
    popup.append(
        makeElement("strong", "", `${weather.name}, ${weather.state}`),
        makeElement("p", "", `${weather.weather_event}: ${weather.condition}`),
        makeElement(
            "p",
            "",
            `${displayValue(weather.temperature_c, "°C")} · rain ${displayValue(weather.precipitation_mm, " mm")}`
        ),
        makeElement(
            "small",
            "",
            `Observed ${weather.observed_at} · ${weatherSourceLabel(weather)}${weatherCacheLabel(weather)}`
        )
    );
    return popup;
}

function openMeteoCooldownMessage() {
    const secondsRemaining = Math.ceil((openMeteoClientRetryUntil - Date.now()) / 1000);
    return secondsRemaining > 0
        ? `Open-Meteo rate limit: automatic retries paused for about ${Math.ceil(secondsRemaining / 60)} minute(s).`
        : "";
}

function renderIndiaWeather(items) {
    const grid = document.querySelector("#india-weather-grid");
    grid.replaceChildren();
    if (!items.length) {
        grid.append(makeElement("p", "empty-message", "No weather observations available."));
        return;
    }

    items.forEach((weather) => {
        const card = makeElement("article", "weather-city-card");
        card.append(
            makeElement("strong", "", `${weather.name}, ${weather.state}`),
            makeElement("span", "weather-city-temperature", displayValue(weather.temperature_c, "°C")),
            makeElement("span", "", `${weather.weather_event} · ${weather.condition}`),
            makeElement(
                "small",
                "",
                `Rain ${displayValue(weather.precipitation_mm, " mm")} · Wind ${displayValue(weather.wind_speed_kmh, " km/h")} · Visibility ${displayValue(weather.visibility_m, " m")}`
            ),
            makeElement(
                "small",
                "",
                `Observed ${formatTime(weather.observed_at)}${weatherCacheLabel(weather)}`
            )
        );
        if (weather.signals.length) {
            card.append(makeElement("small", "weather-signals", weather.signals.join(" · ")));
        }
        grid.append(card);
    });

    if (weatherMarkers) {
        weatherMarkers.clearLayers();
        items.forEach((weather) => {
            if (!Number.isFinite(weather.latitude) || !Number.isFinite(weather.longitude)) return;
            const alertCondition = weather.signals.length > 0;
            window.L.circleMarker([weather.latitude, weather.longitude], {
                radius: 8,
                color: alertCondition ? "#b45309" : "#0284c7",
                fillColor: alertCondition ? "#f59e0b" : "#38bdf8",
                fillOpacity: 0.85,
                weight: 2
            }).bindPopup(makeWeatherPopup(weather)).addTo(weatherMarkers);
        });
    }
}

function appendPopupLine(parent, label, value) {
    const line = makeElement("p", "", "");
    line.append(makeElement("strong", "", `${label}: `), document.createTextNode(value));
    parent.append(line);
}

function renderLocationWeather(parent, weather) {
    parent.append(makeElement("h4", "", "Current weather"));
    appendPopupLine(parent, "Condition", weather.condition);
    appendPopupLine(parent, "Temperature", displayValue(weather.temperature_c, "°C"));
    appendPopupLine(parent, "Feels like", displayValue(weather.apparent_temperature_c, "°C"));
    appendPopupLine(parent, "Humidity", displayValue(weather.humidity_percent, "%"));
    appendPopupLine(parent, "Rain", displayValue(weather.precipitation_mm, " mm"));
    appendPopupLine(parent, "Wind", displayValue(weather.wind_speed_kmh, " km/h"));
    const fogText = weather.weather_code === 45 || weather.weather_code === 48 ||
        (Number.isFinite(weather.visibility_m) && weather.visibility_m < 1000)
        ? `Fog/low visibility likely · ${displayValue(weather.visibility_m, " m")}`
        : `No fog code · visibility ${displayValue(weather.visibility_m, " m")}`;
    appendPopupLine(parent, "Fog / visibility", fogText);
    parent.append(makeElement(
        "small",
        "",
        `Observed ${formatTime(weather.observed_at)} · ${weatherSourceLabel(weather)}${weatherCacheLabel(weather)}`
    ));

    parent.append(makeElement("h4", "", "5-day forecast"));
    if (!Array.isArray(weather.forecast) || !weather.forecast.length) {
        parent.append(makeElement("p", "empty-message", "Forecast is not available in the weather API response."));
        return;
    }
    const forecast = makeElement("ul", "location-forecast");
    weather.forecast.forEach((day) => {
        const item = makeElement("li");
        const date = new Date(`${day.date}T00:00:00Z`);
        const label = Number.isNaN(date.getTime())
            ? day.date
            : new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" }).format(date);
        item.append(
            makeElement("strong", "", label),
            makeElement("span", "", day.condition || "Conditions unavailable"),
            makeElement("span", "", `${displayValue(day.temperature_min_c, "°C")} – ${displayValue(day.temperature_max_c, "°C")}`),
            makeElement("small", "", `Rain chance ${displayValue(day.precipitation_probability_percent, "%")} · ${displayValue(day.precipitation_sum_mm, " mm")}`)
        );
        forecast.append(item);
    });
    parent.append(forecast);
}

function renderLocationEarthquakes(parent, data) {
    parent.append(makeElement("h4", "", `Nearby earthquakes · ${data.radius_km} km / last ${data.days} days`));
    if (!data.items.length) {
        parent.append(makeElement("p", "empty-message", `No USGS events of magnitude ${data.minimum_magnitude}+ found in this area and period.`));
        return;
    }
    const list = makeElement("ul", "location-earthquakes");
    data.items.slice(0, 5).forEach((quake) => {
        const item = makeElement("li");
        item.append(
            makeElement("strong", "", `M ${displayValue(quake.magnitude)}`),
            makeElement("span", "", quake.place),
            makeElement("small", "", `${formatTime(quake.occurred_at)} · Depth ${displayValue(quake.depth_km, " km")}`)
        );
        if (quake.source_url.startsWith("https://earthquake.usgs.gov/")) {
            const link = makeElement("a", "", "Open USGS event");
            link.href = quake.source_url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            item.append(link);
        }
        list.append(item);
    });
        parent.append(list);
}

async function loadMapLocation(location, content) {
    content.replaceChildren(makeElement("p", "", "Loading weather and nearby earthquake information…"));
    const params = new URLSearchParams({
        latitude: String(location.latitude),
        longitude: String(location.longitude)
    });
    const quakeParams = new URLSearchParams({
        latitude: String(location.latitude),
        longitude: String(location.longitude),
        radius_km: "200",
        days: "30",
        minimum_magnitude: "2.5"
    });
    const [weatherResult, earthquakeResult] = await Promise.allSettled([
        openMeteoCooldownMessage()
            ? Promise.reject(new Error(openMeteoCooldownMessage()))
            : requestJson(`/api/live-weather?${params}`),
        requestJson(`/api/earthquakes/nearby?${quakeParams}`)
    ]);
    content.replaceChildren(makeElement("strong", "", `${location.name}, ${location.country}`));
    appendPopupLine(content, "Coordinates", `${location.latitude.toFixed(3)}, ${location.longitude.toFixed(3)}`);
    if (weatherResult.status === "fulfilled") {
        renderLocationWeather(content, weatherResult.value);
    } else {
        content.append(makeElement("p", "error-message", `Weather unavailable: ${String(weatherResult.reason)}`));
    }
    if (earthquakeResult.status === "fulfilled") {
        renderLocationEarthquakes(content, earthquakeResult.value);
        content.append(makeElement("small", "", `Source: USGS · Retrieved ${formatTime(earthquakeResult.value.retrieved_at)} · ${earthquakeResult.value.note}`));
    } else {
        content.append(makeElement("p", "error-message", `Nearby earthquake data unavailable: ${String(earthquakeResult.reason)}`));
    }
}

function setMapScope(scope) {
    if (!map || !placeMarkers) return;
    const showIndiaLayers = scope === "india";
    [markers, weatherMarkers, earthquakeMarkers].forEach((layer) => {
        if (!layer) return;
        if (showIndiaLayers) layer.addTo(map);
        else map.removeLayer(layer);
    });
    placeMarkers.clearLayers();
    mapLocations[scope].forEach((location) => {
        const content = makeElement("div", "map-popup");
        const marker = window.L.circleMarker([location.latitude, location.longitude], {
            radius: scope === "india" ? 7 : 6,
            color: scope === "india" ? "#075985" : "#5b21b6",
            fillColor: scope === "india" ? "#38bdf8" : "#a78bfa",
            fillOpacity: 0.95,
            weight: 2
        }).bindPopup(content, { maxWidth: 340 }).bindTooltip(location.name);
        marker.on("popupopen", () => loadMapLocation(location, content));
        marker.addTo(placeMarkers);
    });
    const indiaButton = document.querySelector("#india-map-button");
    const worldButton = document.querySelector("#world-map-button");
    indiaButton.setAttribute("aria-pressed", String(showIndiaLayers));
    worldButton.setAttribute("aria-pressed", String(!showIndiaLayers));
    document.querySelector("#map-heading").textContent = showIndiaLayers ? "India Weather Map" : "World Weather Map";
    document.querySelector("#map-location-status").textContent = showIndiaLayers
        ? "Tap any of 15 major Indian city markers for current weather, fog/visibility, a five-day forecast, and nearby USGS earthquakes."
        : "Tap any of 24 major world city markers for current weather, fog/visibility, a five-day forecast, and nearby USGS earthquakes.";
    map.setView(showIndiaLayers ? [22.5, 78.9] : [20, 0], showIndiaLayers ? 4.7 : 2);
    map.invalidateSize();
}

async function loadIndiaWeather() {
    const statusMessage = document.querySelector("#weather-feed-status");
    const cooldownMessage = openMeteoCooldownMessage();
    if (cooldownMessage) {
        statusMessage.textContent = cooldownMessage;
        statusMessage.classList.add("error-message");
        return;
    }
    statusMessage.textContent = "Updating Open-Meteo observations…";
    statusMessage.classList.remove("error-message");
    const data = await requestJson("/api/weather/india");
    renderIndiaWeather(data.items);
    const firstError = data.partial_errors?.[0];
    const cachedCount = data.items.filter((item) => item.cache_status !== "live").length;
    statusMessage.textContent = `${data.total} city observations · Retrieved ${formatTime(data.retrieved_at)}` +
        (cachedCount ? ` · ${cachedCount} cached` : "") +
        (firstError ? ` · Some cities unavailable (${data.partial_errors.length})` : "");
    if (data.partial_errors?.length) statusMessage.classList.add("error-message");
}

function renderEarthquakes(items) {
    const list = document.querySelector("#earthquake-list");
    list.replaceChildren();
    if (!items.length) {
        list.append(makeElement("p", "empty-message", "No matching India earthquakes in the current USGS feed."));
    } else {
        items.slice(0, 12).forEach((quake) => {
            const card = makeElement("article", "earthquake-item");
            card.append(
                makeElement("strong", "", `M ${displayValue(quake.magnitude)}`),
                makeElement("span", "", quake.place),
                makeElement("small", "", `${formatTime(quake.occurred_at)} · Depth ${displayValue(quake.depth_km, " km")}`)
            );
            list.append(card);
        });
    }

    if (earthquakeMarkers) {
        earthquakeMarkers.clearLayers();
        items.forEach((quake) => {
            if (!Number.isFinite(quake.latitude) || !Number.isFinite(quake.longitude)) return;
            const popup = makeElement("div", "map-popup");
            popup.append(
                makeElement("strong", "", `USGS earthquake · M ${displayValue(quake.magnitude)}`),
                makeElement("p", "", quake.place),
                makeElement("small", "", `${formatTime(quake.occurred_at)} · Retrieved ${formatTime(quake.retrieved_at)}`)
            );
            const marker = window.L.circleMarker([quake.latitude, quake.longitude], {
                radius: 7 + Math.min(quake.magnitude || 0, 8),
                color: "#991b1b",
                fillColor: "#ef4444",
                fillOpacity: 0.8,
                weight: 2
            }).bindPopup(popup);
            if (quake.source_url.startsWith("https://earthquake.usgs.gov/")) {
                const link = makeElement("a", "", "Open USGS event");
                link.href = quake.source_url;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                popup.append(link);
            }
            marker.addTo(earthquakeMarkers);
        });
    }
}

async function loadEarthquakes() {
    const statusMessage = document.querySelector("#earthquake-feed-status");
    statusMessage.textContent = "Updating USGS India-region query…";
    statusMessage.classList.remove("error-message");
    const minimumMagnitude = document.querySelector("#earthquake-minimum-magnitude").value;
    const data = await requestJson(
        `/api/earthquakes/india?minimum_magnitude=${encodeURIComponent(minimumMagnitude)}`
    );
    renderEarthquakes(data.items);
    statusMessage.textContent = `${data.total} India events · Retrieved ${formatTime(data.retrieved_at)}`;
}

function nasaDisplay(value, field, units) {
    return Number.isFinite(value)
        ? `${value} ${units[field] || ""}`.trim()
        : "Unavailable";
}

async function loadNasaPower(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const cityName = values.get("city");
    const coordinates = indiaCityCoordinates[cityName];
    const statusMessage = document.querySelector("#nasa-power-status");
    const resultContainer = document.querySelector("#nasa-power-results");
    if (!coordinates) {
        statusMessage.textContent = "Choose a supported India city.";
        statusMessage.classList.add("error-message");
        return;
    }

    const params = new URLSearchParams({
        latitude: String(coordinates.latitude),
        longitude: String(coordinates.longitude),
        start_date: values.get("start_date"),
        end_date: values.get("end_date")
    });
    statusMessage.textContent = "Requesting NASA POWER daily data…";
    statusMessage.classList.remove("error-message");
    resultContainer.replaceChildren();
    try {
        const data = await requestJson(`/api/weather/nasa-power/daily?${params}`);
        if (!data.items.length) {
            resultContainer.append(makeElement("p", "empty-message", "NASA POWER returned no daily values for this period."));
        }
        data.items.forEach((day) => {
            const card = makeElement("article", "nasa-power-day");
            card.append(
                makeElement("strong", "", day.date),
                makeElement("span", "", `Mean ${nasaDisplay(day.temperature_mean_c, "temperature_mean_c", data.units)}`),
                makeElement("small", "", `Min / max ${nasaDisplay(day.temperature_min_c, "temperature_min_c", data.units)} / ${nasaDisplay(day.temperature_max_c, "temperature_max_c", data.units)}`),
                makeElement("small", "", `Rain ${nasaDisplay(day.precipitation_mm_day, "precipitation_mm_day", data.units)} · Humidity ${nasaDisplay(day.humidity_percent, "humidity_percent", data.units)}`),
                makeElement("small", "", `Wind ${nasaDisplay(day.wind_speed_m_s, "wind_speed_m_s", data.units)}`)
            );
            resultContainer.append(card);
        });
        statusMessage.textContent =
            `${cityName} · ${data.total} daily records · Retrieved ${formatTime(data.retrieved_at)} · ${data.source}`;
    } catch (error) {
        statusMessage.textContent = `NASA POWER data unavailable: ${error.message}`;
        statusMessage.classList.add("error-message");
    }
}

async function loadSummary() {
    const summary = await requestJson("/api/summary");
    Object.entries(summary).forEach(([key, value]) => {
        const metric = document.querySelector(`[data-metric="${key}"]`);
        if (metric) metric.textContent = Number(value).toLocaleString();
    });
    document.querySelector("#sample-data-notice").hidden = !summary.includes_demo_data;
    document.querySelector("#summary-error").hidden = true;
}

async function loadEvents() {
    const loadVersion = ++eventsLoadVersion;
    const params = new URLSearchParams();
    const eventType = document.querySelector("#event-filter").value;
    const reportStatus = document.querySelector("#status-filter").value;
    const state = document.querySelector("#state-filter").value.trim();
    const location = document.querySelector("#location-filter").value.trim();
    const fromDate = document.querySelector("#from-date-filter").value;
    const toDate = document.querySelector("#to-date-filter").value;
    if (eventType) params.set("event", eventType);
    if (reportStatus) params.set("status", reportStatus);
    if (state) params.set("state", state);
    if (location) params.set("location", location);
    if (fromDate) params.set("from_date", fromDate);
    if (toDate) params.set("to_date", toDate);
    const suffix = params.size ? `?${params}` : "";
    const data = await requestJson(`/api/events${suffix}`);
    if (loadVersion !== eventsLoadVersion) return;
    const eventCards = renderEvents(data.items);
    void loadEventLocationData(data.items, eventCards, loadVersion);
}

async function requestEventLocationData(locations) {
    const weatherParams = new URLSearchParams();
    locations.forEach(({ event }) => {
        weatherParams.append("latitude", String(event.latitude));
        weatherParams.append("longitude", String(event.longitude));
    });
    const cooldownMessage = openMeteoCooldownMessage();
    const weatherRequest = (cooldownMessage
        ? Promise.reject(new Error(cooldownMessage))
        : requestJson(`/api/live-weather/batch?${weatherParams}`))
        .then((response) => {
            const observations = new Map();
            response.items.forEach((weather) => {
                observations.set(
                    `${weather.requested_latitude},${weather.requested_longitude}`,
                    { weather, weatherError: null }
                );
            });
            response.partial_errors.forEach((error) => {
                observations.set(
                    `${error.latitude},${error.longitude}`,
                    { weather: null, weatherError: error.detail }
                );
            });
            return observations;
        })
        .catch((error) => new Map(
            locations.map(({ event }) => [
                `${event.latitude},${event.longitude}`,
                { weather: null, weatherError: String(error) }
            ])
        ));

    const earthquakeResults = new Map();
    let nextIndex = 0;
    const earthquakeWorker = async () => {
        while (nextIndex < locations.length) {
            const index = nextIndex++;
            const { event } = locations[index];
            const key = `${event.latitude},${event.longitude}`;
            const params = new URLSearchParams({
                latitude: String(event.latitude),
                longitude: String(event.longitude),
                radius_km: "200",
                days: "30",
                minimum_magnitude: "2.5"
            });
            try {
                earthquakeResults.set(key, {
                    earthquakes: await requestJson(`/api/earthquakes/nearby?${params}`),
                    earthquakeError: null
                });
            } catch (error) {
                earthquakeResults.set(key, {
                    earthquakes: null,
                    earthquakeError: String(error)
                });
            }
        }
    };
    await Promise.all([
        weatherRequest,
        ...Array.from(
            { length: Math.min(4, locations.length) },
            () => earthquakeWorker()
        )
    ]);
    const weatherResults = await weatherRequest;
    return new Map(locations.map(({ event }) => {
        const key = `${event.latitude},${event.longitude}`;
        return [
            key,
            {
                ...weatherResults.get(key),
                ...earthquakeResults.get(key)
            }
        ];
    }));
}

function renderEventLocationData(container, report, data) {
    container.replaceChildren();
    container.append(
        makeElement(
            "strong",
            "",
            `Location context · ${report.latitude.toFixed(4)}, ${report.longitude.toFixed(4)}`
        )
    );

    if (data.weather) {
        const weather = data.weather;
        container.append(makeElement(
            "p",
            "",
            `Open-Meteo current: ${weather.weather_event} · ${weather.condition} · ` +
                `${displayValue(weather.temperature_c, "°C")} · rain ${displayValue(weather.precipitation_mm, " mm")}`
        ));
        container.append(makeElement(
            "small",
            "",
            `Feels like ${displayValue(weather.apparent_temperature_c, "°C")} · ` +
                `humidity ${displayValue(weather.humidity_percent, "%")} · ` +
                `wind ${displayValue(weather.wind_speed_kmh, " km/h")} · ` +
                `visibility ${displayValue(weather.visibility_m, " m")}`
        ));
        container.append(makeElement(
            "small",
            "",
            `Observed ${formatTime(weather.observed_at)} · current conditions, not verification of this report` +
                weatherCacheLabel(weather)
        ));
        if (weather.signals.length) {
            container.append(makeElement("small", "weather-signals", weather.signals.join(" · ")));
        }
    } else {
        container.append(makeElement("p", "error-message", `Open-Meteo unavailable: ${data.weatherError}`));
    }

    if (data.earthquakes) {
        const feed = data.earthquakes;
        const quakeSummary = feed.total
            ? `USGS: ${feed.total} event${feed.total === 1 ? "" : "s"} ≥ M2.5 within 200 km in the last 30 days`
            : "USGS: no events ≥ M2.5 within 200 km in the last 30 days";
        container.append(makeElement("p", "", quakeSummary));
        feed.items.slice(0, 3).forEach((quake) => {
            container.append(makeElement(
                "small",
                "",
                `M ${displayValue(quake.magnitude)} · ${quake.place} · ${formatTime(quake.occurred_at)}`
            ));
        });
        container.append(makeElement(
            "small",
            "",
            `Source: USGS · Retrieved ${formatTime(feed.retrieved_at)} · a zero-result feed is not proof of no earthquake`
        ));
    } else {
        container.append(makeElement("p", "error-message", `USGS nearby data unavailable: ${data.earthquakeError}`));
    }
}

async function loadEventLocationData(events, eventCards, loadVersion) {
    const locations = events
        .map((event, index) => ({ event, card: eventCards[index] }))
        .filter(({ event }) => Number.isFinite(event.latitude) && Number.isFinite(event.longitude));
    if (!locations.length) return;
    const uniqueLocations = new Map();
    locations.forEach(({ event }) => {
        const key = `${event.latitude},${event.longitude}`;
        if (!uniqueLocations.has(key)) uniqueLocations.set(key, event);
    });
    const now = Date.now();
    const cached = new Map();
    const uncachedEvents = [];
    uniqueLocations.forEach((event, key) => {
        const entry = eventLocationDataCache.get(key);
        if (entry && now - entry.retrievedAt < EVENT_LOCATION_DATA_TTL_MS) {
            cached.set(key, entry.data);
        } else {
            uncachedEvents.push({ event });
        }
    });

    let fresh = new Map();
    if (uncachedEvents.length) {
        const requestKey = uncachedEvents
            .map(({ event }) => `${event.latitude},${event.longitude}`)
            .sort()
            .join("|");
        let request = eventLocationDataRequests.get(requestKey);
        if (!request) {
            request = requestEventLocationData(uncachedEvents)
                .finally(() => eventLocationDataRequests.delete(requestKey));
            eventLocationDataRequests.set(requestKey, request);
        }
        fresh = await request;
        fresh.forEach((data, key) => {
            eventLocationDataCache.set(key, { data, retrievedAt: Date.now() });
        });
    }

    if (loadVersion !== eventsLoadVersion) return;
    locations.forEach(({ event, card }) => {
        if (!card.isConnected) return;
        const key = `${event.latitude},${event.longitude}`;
        const data = cached.get(key) || fresh.get(key);
        if (data) {
            renderEventLocationData(card.querySelector(".event-location-data"), event, data);
        }
    });
}

async function loadReportsTable() {
    const data = await requestJson("/api/events?limit=100");
    const body = document.querySelector(".reports-table-body");
    body.replaceChildren();
    if (!data.items.length) {
        const row = makeElement("tr");
        const cell = makeElement("td", "", "No reports available.");
        cell.colSpan = 7;
        row.append(cell);
        body.append(row);
        return;
    }

    data.items.forEach((report) => {
        const row = makeElement("tr");
        [
            report.location,
            report.event,
            formatTime(report.time),
            report.source,
            report.is_demo ? `${report.status} · Sample` : report.status,
            report.confidence === null ? "Not verified" : `${report.confidence}%`,
            report.ai_classification
                ? `${report.ai_classification.disaster_label} (score ${Math.round(report.ai_classification.disaster_score * 100)}%); ${report.ai_classification.social_event_type}`
                : report.is_demo
                    ? "Sample only"
                    : report.ai_classification_status === "model_unavailable"
                        ? "Model not trained"
                        : "Not requested"
        ].forEach((value) => row.append(makeElement("td", "", value)));
        body.append(row);
    });
}

async function loadAnalytics() {
    const data = await requestJson("/api/analytics");
    const list = document.querySelector(".distribution-list");
    list.replaceChildren();
    if (!data.distribution.length) {
        list.append(makeElement("p", "empty-message", "No event analytics available."));
        return;
    }
    data.distribution.forEach((entry) => {
        const row = makeElement("div", "distribution-row");
        const label = makeElement("span", "", entry.event);
        const barTrack = makeElement("div", "distribution-bar-track");
        const bar = makeElement("div", "distribution-bar");
        bar.style.width = `${entry.percentage}%`;
        barTrack.append(bar);
        row.append(label, barTrack, makeElement("span", "", `${entry.percentage}%`));
        list.append(row);
    });
}

async function loadAlerts() {
    const data = await requestJson("/api/alerts?status=active");
    const list = document.querySelector(".alerts-list");
    list.replaceChildren();
    if (!data.items.length) {
        list.append(makeElement("p", "empty-message", "No active alerts."));
        return;
    }
    data.items.forEach((alert) => {
        const item = makeElement("article", `alert-item ${alert.severity}`);
        item.append(
            makeElement("strong", "", alert.severity.toUpperCase()),
            makeElement("span", "", alert.message)
        );
        list.append(item);
    });
}

async function loadLiveWeather(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const result = document.querySelector(".live-weather-result");
    const values = new FormData(form);
    const params = new URLSearchParams({
        latitude: values.get("latitude"),
        longitude: values.get("longitude"),
        force_refresh: "1"
    });
    result.textContent = "Checking live weather…";
    result.className = "live-weather-result";
    try {
        const weather = await requestJson(`/api/live-weather?${params}`);
        result.textContent = `${weather.condition} · ${displayValue(weather.temperature_c, "°C")}` +
            ` (feels like ${displayValue(weather.apparent_temperature_c, "°C")}), humidity ${displayValue(weather.humidity_percent, "%")}` +
            `, rain ${displayValue(weather.precipitation_mm, " mm")}, wind ${displayValue(weather.wind_speed_kmh, " km/h")}` +
            `, visibility ${displayValue(weather.visibility_m, " m")}` +
            ` · ${weatherSourceLabel(weather)} · observed ${formatTime(weather.observed_at)}` +
            weatherCacheLabel(weather) +
            (weather.provider_error ? ` · ${weather.provider_error}` : "");
    } catch (error) {
        result.textContent = `Live weather unavailable: ${error.message}`;
        result.classList.add("error-message");
    }
}

async function showLoadError(task, target) {
    try {
        await task();
    } catch (error) {
        target.hidden = false;
        if (target.tagName === "P") {
            target.textContent = error.message;
        } else if (target.tagName === "TBODY") {
            const row = makeElement("tr");
            const cell = makeElement("td", "error-message", error.message);
            cell.colSpan = 7;
            row.append(cell);
            target.replaceChildren(row);
        } else {
            target.replaceChildren(makeElement("p", "error-message", error.message));
        }
    }
}

function navigateToDashboardSection(item) {
    const targetSelector = item.getAttribute("data-target");
    const target = targetSelector && document.querySelector(targetSelector);
    if (!target) return;
    const details = target.closest("details");
    if (details) details.open = true;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.querySelectorAll("#sidebar [data-target]").forEach((item) => {
    item.addEventListener("click", () => navigateToDashboardSection(item));
    item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            navigateToDashboardSection(item);
        }
    });
});

async function refreshDashboard() {
    await Promise.all([
        showLoadError(loadSummary, document.querySelector("#summary-error")),
        showLoadError(loadEvents, eventsList),
        showLoadError(loadReportsTable, document.querySelector(".reports-table-body")),
        showLoadError(loadAnalytics, document.querySelector(".distribution-list")),
        showLoadError(loadAlerts, document.querySelector(".alerts-list")),
        showLoadError(loadIndiaWeather, document.querySelector("#weather-feed-status")),
        showLoadError(loadEarthquakes, document.querySelector("#earthquake-feed-status"))
    ]);
    fitMapToSources();
}

document.querySelector("#apply-filters").addEventListener("click", () =>
    showLoadError(loadEvents, eventsList)
);
document.querySelector("#india-map-button").addEventListener("click", () => setMapScope("india"));
document.querySelector("#world-map-button").addEventListener("click", () => setMapScope("world"));
document.querySelector("#live-weather-form").addEventListener("submit", loadLiveWeather);
document.querySelector("#refresh-weather").addEventListener("click", () =>
    showLoadError(loadIndiaWeather, document.querySelector("#weather-feed-status"))
);
document.querySelector("#earthquake-minimum-magnitude").addEventListener("change", () =>
    showLoadError(loadEarthquakes, document.querySelector("#earthquake-feed-status"))
);
document.querySelector("#nasa-power-form").addEventListener("submit", loadNasaPower);
document.querySelector("#new-report-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formMessage = form.querySelector(".form-message");
    const values = new FormData(form);
    const payload = {
        location: values.get("location"),
        state: values.get("state"),
        event: values.get("event"),
        description: values.get("description"),
        time: new Date(values.get("time")).toISOString(),
        severity: values.get("severity"),
        latitude: Number(values.get("latitude")),
        longitude: Number(values.get("longitude"))
    };

    formMessage.textContent = "Submitting report…";
    formMessage.className = "form-message";
    try {
        const created = await requestJson("/api/events", {
            method: "POST",
            body: JSON.stringify(payload)
        });
        const classificationMessage = created.ai_classification
            ? ` AI text signal: ${created.ai_classification.disaster_label} / ` +
                `${created.ai_classification.social_event_type}; this is not verification.`
            : created.ai_classification_status === "model_unavailable"
                ? " AI model is unavailable; report was saved without classification."
                : "";
        formMessage.textContent = (created.duplicate_detected
            ? "Possible duplicate report saved."
            : "Report submitted successfully.") + classificationMessage;
        form.reset();
        await refreshDashboard();
    } catch (error) {
        formMessage.textContent = `Could not submit report: ${error.message}`;
        formMessage.classList.add("error-message");
    }
});

setMapScope("india");
refreshDashboard();
const nasaEndDate = new Date();
const nasaStartDate = new Date(nasaEndDate);
nasaStartDate.setUTCDate(nasaStartDate.getUTCDate() - 6);
document.querySelector("#nasa-power-form [name='start_date']").value =
    nasaStartDate.toISOString().slice(0, 10);
document.querySelector("#nasa-power-form [name='end_date']").value =
    nasaEndDate.toISOString().slice(0, 10);
window.setInterval(() => {
    showLoadError(loadIndiaWeather, document.querySelector("#weather-feed-status"));
    showLoadError(loadEarthquakes, document.querySelector("#earthquake-feed-status"));
}, 15 * 60 * 1000);
