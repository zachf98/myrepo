const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const message = payload?.detail || payload?.error || "Request failed";
    throw new Error(message);
  }

  return payload;
}

export function fetchEvents() {
  return request("/api/events");
}

export function analyzeEvent(eventUrl) {
  return request("/api/analyze", {
    method: "POST",
    body: JSON.stringify({ eventUrl }),
  });
}

