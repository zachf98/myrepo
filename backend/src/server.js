const express = require("express");
const cors = require("cors");
const { getEventList } = require("./services/ufcStatsService");
const { analyzeEvent } = require("./services/analyzeService");

const app = express();
const PORT = Number(process.env.PORT || 8080);

app.use(cors());
app.use(express.json());

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, service: "ufc-betting-edge-api" });
});

app.get("/api/events", async (_req, res) => {
  try {
    const events = await getEventList();
    res.json({
      events,
      count: events.length,
      source: "UFCStats public event pages",
    });
  } catch (error) {
    res.status(500).json({
      error: "Failed to fetch UFC events",
      detail: error.message,
    });
  }
});

app.post("/api/analyze", async (req, res) => {
  const { eventUrl } = req.body || {};
  if (!eventUrl) {
    return res.status(400).json({ error: "eventUrl is required" });
  }

  try {
    const analysis = await analyzeEvent(eventUrl);
    return res.json(analysis);
  } catch (error) {
    return res.status(500).json({
      error: "Failed to analyze event",
      detail: error.message,
    });
  }
});

app.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`Backend listening on http://localhost:${PORT}`);
});
