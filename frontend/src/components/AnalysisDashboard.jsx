import { useMemo, useState } from "react";

function percent(value) {
  if (!Number.isFinite(value)) return "N/A";
  return `${(value * 100).toFixed(1)}%`;
}

function edgeClass(edge) {
  if (!Number.isFinite(edge)) return "edge-neutral";
  if (edge > 0) return "edge-positive";
  if (edge < 0) return "edge-negative";
  return "edge-neutral";
}

function edgeLabel(edge) {
  if (!Number.isFinite(edge)) return "N/A";
  return `${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(1)}%`;
}

function evLabel(ev) {
  if (!Number.isFinite(ev)) return "N/A";
  return `${ev >= 0 ? "+" : ""}${(ev * 100).toFixed(1)}%`;
}

function methodRows(methods) {
  if (!methods) return [];
  return [
    { label: "KO/TKO", key: "ko_tko" },
    { label: "Submission", key: "submission" },
    { label: "Decision", key: "decision" },
  ].map((entry) => ({
    ...entry,
    value: methods[entry.key],
  }));
}

function roundRows(rounds) {
  if (!rounds) return [];
  return [
    { label: "Round 1 Finish", key: "round1" },
    { label: "Round 2 Finish", key: "round2" },
    { label: "Round 3+ Finish", key: "round3_plus" },
    { label: "Decision", key: "decision" },
  ].map((entry) => ({
    ...entry,
    value: rounds[entry.key],
  }));
}

function methodLabel(method) {
  if (method === "ko_tko") return "KO/TKO";
  if (method === "submission") return "Submission";
  if (method === "decision") return "Decision";
  return method;
}

function FightCard({ fight, viewMode }) {
  const fighterAName = fight.fighters?.fighterA?.name || "Fighter A";
  const fighterBName = fight.fighters?.fighterB?.name || "Fighter B";
  const marketOddsA = fight.market?.odds?.fighterA;
  const marketOddsB = fight.market?.odds?.fighterB;
  const impliedA = fight.market?.implied?.noVigFighterA ?? fight.market?.implied?.fighterA;
  const impliedB = fight.market?.implied?.noVigFighterB ?? fight.market?.implied?.fighterB;
  const modelWinA = fight.model?.winProbabilities?.fighterA;
  const modelWinB = fight.model?.winProbabilities?.fighterB;
  const edgeA = fight.edge?.fighterA;
  const edgeB = fight.edge?.fighterB;
  const evA = fight.ev?.fighterA;
  const evB = fight.ev?.fighterB;

  const methodA = fight.model?.methodProbabilities?.fighterA;
  const methodB = fight.model?.methodProbabilities?.fighterB;
  const roundA = fight.model?.roundProbabilities?.fighterA;
  const roundB = fight.model?.roundProbabilities?.fighterB;
  const roundFight = fight.model?.roundProbabilities?.fightTotal;
  const methodAlignment = fight.model?.methodAlignment;
  const breakdown = fight.model?.featureBreakdown || {};

  return (
    <article className="fight-card">
      <header className="fight-card-header">
        <div>
          <h3>{fight.matchup}</h3>
          <p className="fight-subtitle">{fight.weightClass || "Weight class unavailable"}</p>
        </div>
        <div className={`best-edge-pill ${edgeClass(fight.edge?.bestEdge?.edge)}`}>
          Best edge: {fight.edge?.bestEdge ? `${fight.edge.bestEdge.fighter} ${edgeLabel(fight.edge.bestEdge.edge)}` : "N/A"}
        </div>
      </header>

      {viewMode === "win" ? (
        <div className="grid-two">
          <div className="metric-block">
            <h4>Market Odds (No-Vig Implied)</h4>
            <p>
              {fighterAName}: {Number.isFinite(marketOddsA) ? marketOddsA : "N/A"} ({percent(impliedA)})
            </p>
            <p>
              {fighterBName}: {Number.isFinite(marketOddsB) ? marketOddsB : "N/A"} ({percent(impliedB)})
            </p>
          </div>
          <div className="metric-block">
            <h4>Model Win Probabilities</h4>
            <p>{fighterAName}: {percent(modelWinA)}</p>
            <p>{fighterBName}: {percent(modelWinB)}</p>
          </div>
          <div className="metric-block">
            <h4>Edge (Model - Market)</h4>
            <p className={edgeClass(edgeA)}>{fighterAName}: {edgeLabel(edgeA)}</p>
            <p className={edgeClass(edgeB)}>{fighterBName}: {edgeLabel(edgeB)}</p>
          </div>
          <div className="metric-block">
            <h4>Expected Value (ROI per 1u)</h4>
            <p className={edgeClass(evA)}>{fighterAName}: {evLabel(evA)}</p>
            <p className={edgeClass(evB)}>{fighterBName}: {evLabel(evB)}</p>
          </div>
          <div className="metric-block">
            <h4>Data Notes</h4>
            <p className="small-note">{fight.market?.source || "Unknown source"}</p>
            {fight.market?.note ? <p className="small-note">{fight.market.note}</p> : null}
            {fight.market?.methodPropsNote ? <p className="small-note">{fight.market.methodPropsNote}</p> : null}
          </div>
          <div className="metric-block">
            <h4>Model Drivers</h4>
            <p className="small-note">Recency: {edgeLabel(breakdown.recencyDiff)}</p>
            <p className="small-note">Activity: {edgeLabel(breakdown.activityDiff)}</p>
            <p className="small-note">Age/Prime: {edgeLabel(breakdown.agePrimeDiff)}</p>
            <p className="small-note">Decision skill: {edgeLabel(breakdown.decisionSkillDiff)}</p>
            <p className="small-note">Round durability: {edgeLabel(breakdown.roundDurabilityDiff)}</p>
          </div>
        </div>
      ) : (
        <div className="grid-two">
          <div className="metric-block stacked-metrics">
            <div>
              <h4>{fighterAName} - Method of Victory</h4>
              {methodRows(methodA).map((row) => (
                <p key={`${fighterAName}-${row.key}`}>
                  {row.label}: {percent(row.value)}
                </p>
              ))}
            </div>
            <div>
              <h4>{fighterAName} - Round Breakdown</h4>
              {roundRows(roundA).map((row) => (
                <p key={`${fighterAName}-round-${row.key}`}>
                  {row.label}: {percent(row.value)}
                </p>
              ))}
            </div>
          </div>
          <div className="metric-block stacked-metrics">
            <div>
              <h4>{fighterBName} - Method of Victory</h4>
              {methodRows(methodB).map((row) => (
                <p key={`${fighterBName}-${row.key}`}>
                  {row.label}: {percent(row.value)}
                </p>
              ))}
            </div>
            <div>
              <h4>{fighterBName} - Round Breakdown</h4>
              {roundRows(roundB).map((row) => (
                <p key={`${fighterBName}-round-${row.key}`}>
                  {row.label}: {percent(row.value)}
                </p>
              ))}
            </div>
          </div>
          <div className="metric-block">
            <h4>Fight-Level Round Outlook</h4>
            {roundRows(roundFight).map((row) => (
              <p key={`fight-round-${row.key}`}>
                {row.label}: {percent(row.value)}
              </p>
            ))}
          </div>
        </div>
      )}
      {fight.insightBlurb ? (
        <div className="metric-block value-blurb">
          <h4>Expected Fight Script</h4>
          <p>{fight.insightBlurb}</p>
          {methodAlignment?.alignments?.length ? (
            <div className="alignment-list">
              <h4>Favorite Win vs Underdog Loss Method Matchup</h4>
              <p className="small-note">
                Favorite: {methodAlignment.favoriteName} · Underdog: {methodAlignment.underdogName}
              </p>
              <p className="small-note">
                Source:{" "}
                {methodAlignment.source === "ufc-primary"
                  ? "UFC-only method history"
                  : "UFC-first with pre-UFC fallback where UFC samples are thin"}
              </p>
              {methodAlignment.alignments.slice(0, 3).map((entry) => (
                <p key={`${fight.fightId}-${entry.method}`} className="small-note">
                  {methodLabel(entry.method)}: favorite win {percent(entry.favoriteWinRate)} ·
                  underdog loss {percent(entry.underdogLossRate)} · align{" "}
                  {entry.linesUp ? "Yes" : "No"}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function AnalysisDashboard({ analysis }) {
  const [viewMode, setViewMode] = useState("win");
  const [browseMode, setBrowseMode] = useState("single");
  const [selectedFightId, setSelectedFightId] = useState(null);

  const fights = useMemo(() => {
    const list = [...(analysis.fights || [])];
    list.sort((a, b) => (b.edge?.bestEdge?.edge ?? -Infinity) - (a.edge?.bestEdge?.edge ?? -Infinity));
    return list;
  }, [analysis.fights]);

  const topEdges = useMemo(() => {
    const rows = [];
    fights.forEach((fight) => {
      if (fight.edge?.bestEdge && Number.isFinite(fight.edge.bestEdge.edge)) {
        rows.push({
          matchup: fight.matchup,
          fighter: fight.edge.bestEdge.fighter,
          edge: fight.edge.bestEdge.edge,
        });
      }
    });
    return rows.slice(0, 5);
  }, [fights]);
  const topValuePlays = analysis.valuePlays || [];
  const selectedFight = useMemo(() => {
    if (!fights.length) return null;
    if (!selectedFightId) return fights[0];
    return fights.find((fight) => fight.fightId === selectedFightId) || fights[0];
  }, [fights, selectedFightId]);
  const selectedFightIndex = useMemo(
    () => fights.findIndex((fight) => fight.fightId === selectedFight?.fightId),
    [fights, selectedFight],
  );
  const fightsToRender = browseMode === "single" ? (selectedFight ? [selectedFight] : []) : fights;

  return (
    <section className="panel analysis-panel">
      <header className="analysis-header">
        <div>
          <h2>{analysis.event?.name || "Event Analysis"}</h2>
          <p className="event-inline-meta">
            {(analysis.event?.metadata || []).join(" · ") || "Event metadata unavailable"}
          </p>
        </div>
        <div className="view-toggle">
          <button
            type="button"
            className={viewMode === "win" ? "toggle-active" : ""}
            onClick={() => setViewMode("win")}
          >
            Win Probability View
          </button>
          <button
            type="button"
            className={viewMode === "method" ? "toggle-active" : ""}
            onClick={() => setViewMode("method")}
          >
            Method of Victory View
          </button>
        </div>
      </header>

      <div className="top-edge-strip">
        <h3>Largest Market Discrepancies</h3>
        {topEdges.length ? (
          <ul>
            {topEdges.map((entry) => (
              <li key={`${entry.matchup}-${entry.fighter}`}>
                <span>{entry.matchup}</span>
                <strong className={edgeClass(entry.edge)}>
                  {entry.fighter} {edgeLabel(entry.edge)}
                </strong>
              </li>
            ))}
          </ul>
        ) : (
          <p>No market-edge values are currently available.</p>
        )}
      </div>

      <div className="top-edge-strip">
        <h3>Best Estimated EV Plays</h3>
        {topValuePlays.length ? (
          <ul>
            {topValuePlays.map((entry) => (
              <li key={`${entry.matchup}-${entry.fighter}`}>
                <span>
                  {entry.matchup} - {entry.fighter}
                </span>
                <strong className={edgeClass(entry.ev)}>
                  {evLabel(entry.ev)} · Win {percent(entry.modelWinProbability)}
                </strong>
              </li>
            ))}
          </ul>
        ) : (
          <p>No positive-EV opportunities with model win probability at or above 40%.</p>
        )}
      </div>

      <div className="top-edge-strip fight-navigator">
        <h3>Fight Navigator</h3>
        <div className="navigator-controls">
          <div className="view-toggle">
            <button
              type="button"
              className={browseMode === "single" ? "toggle-active" : ""}
              onClick={() => setBrowseMode("single")}
            >
              Single Fight View
            </button>
            <button
              type="button"
              className={browseMode === "all" ? "toggle-active" : ""}
              onClick={() => setBrowseMode("all")}
            >
              All Fights View
            </button>
          </div>
          <select
            value={selectedFight?.fightId || ""}
            onChange={(event) => setSelectedFightId(event.target.value)}
          >
            {fights.map((fight, index) => (
              <option key={fight.fightId} value={fight.fightId}>
                {index + 1}. {fight.matchup}
              </option>
            ))}
          </select>
          <div className="nav-buttons">
            <button
              type="button"
              onClick={() => {
                if (!fights.length) return;
                const prevIndex = selectedFightIndex <= 0 ? fights.length - 1 : selectedFightIndex - 1;
                setSelectedFightId(fights[prevIndex].fightId);
              }}
            >
              Previous
            </button>
            <button
              type="button"
              onClick={() => {
                if (!fights.length) return;
                const nextIndex = selectedFightIndex >= fights.length - 1 ? 0 : selectedFightIndex + 1;
                setSelectedFightId(fights[nextIndex].fightId);
              }}
            >
              Next
            </button>
          </div>
        </div>
      </div>

      <div className="fight-list">
        {fightsToRender.map((fight) => (
          <FightCard key={fight.fightId} fight={fight} viewMode={viewMode} />
        ))}
      </div>

      <footer className="analysis-notes">
        {(analysis.notes || []).map((note, index) => (
          <p key={index}>{note}</p>
        ))}
      </footer>
    </section>
  );
}

export default AnalysisDashboard;
