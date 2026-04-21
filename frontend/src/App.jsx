import { useEffect, useMemo, useState } from "react";
import "./App.css";
import { fetchEvents, analyzeEvent } from "./api/client";
import EventSelector from "./components/EventSelector";
import AnalysisDashboard from "./components/AnalysisDashboard";

function App() {
  const [events, setEvents] = useState([]);
  const [selectedEventUrl, setSelectedEventUrl] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function loadEvents() {
      try {
        setLoadingEvents(true);
        setError("");
        const payload = await fetchEvents();
        if (!mounted) return;
        setEvents(payload.events || []);
        const firstUpcoming = (payload.events || []).find((event) => event.category === "upcoming");
        if (firstUpcoming) {
          setSelectedEventUrl(firstUpcoming.eventUrl);
        }
      } catch (err) {
        if (!mounted) return;
        setError(err.message || "Failed to load events.");
      } finally {
        if (mounted) {
          setLoadingEvents(false);
        }
      }
    }
    loadEvents();
    return () => {
      mounted = false;
    };
  }, []);

  const selectedEvent = useMemo(
    () => events.find((event) => event.eventUrl === selectedEventUrl) || null,
    [events, selectedEventUrl],
  );

  async function handleAnalyzeEvent() {
    if (!selectedEventUrl) return;
    try {
      setAnalyzing(true);
      setError("");
      const payload = await analyzeEvent(selectedEventUrl);
      setAnalysis(payload);
    } catch (err) {
      setError(err.message || "Failed to analyze event.");
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <h1>UFC Betting Edge Calculator</h1>
        <p>
          Free-data UFC event analyzer using UFCStats and public market odds snapshots, with
          transparent probability modeling.
        </p>
      </header>

      <section className="panel controls-panel">
        <EventSelector
          events={events}
          selectedEventUrl={selectedEventUrl}
          onEventChange={setSelectedEventUrl}
          selectedEvent={selectedEvent}
          loading={loadingEvents}
        />
        <button
          type="button"
          className="analyze-btn"
          onClick={handleAnalyzeEvent}
          disabled={!selectedEventUrl || loadingEvents || analyzing}
        >
          {analyzing ? "Analyzing Event..." : "Analyze Event"}
        </button>
      </section>

      {error ? <div className="panel error-panel">{error}</div> : null}

      {analysis ? <AnalysisDashboard analysis={analysis} /> : null}
    </main>
  );
}

export default App;
