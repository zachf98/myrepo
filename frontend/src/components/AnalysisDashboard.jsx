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

  const methodA = fight.model?.methodProbabilities?.fighterA;
  const methodB = fight.model?.methodProbabilities?.fighterB;

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
            <h4>Data Notes</h4>
            <p className="small-note">{fight.market?.source || "Unknown source"}</p>
            {fight.market?.note ? <p className="small-note">{fight.market.note}</p> : null}
            {fight.market?.methodPropsNote ? <p className="small-note">{fight.market.methodPropsNote}</p> : null}
          </div>
        </div>
      ) : (
        <div className="grid-two">
          <div className="metric-block">
            <h4>{fighterAName} - Method of Victory</h4>
            {methodRows(methodA).map((row) => (
              <p key={`${fighterAName}-${row.key}`}>
                {row.label}: {percent(row.value)}
              </p>
            ))}
          </div>
          <div className="metric-block">
            <h4>{fighterBName} - Method of Victory</h4>
            {methodRows(methodB).map((row) => (
              <p key={`${fighterBName}-${row.key}`}>
                {row.label}: {percent(row.value)}
              </p>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

function AnalysisDashboard({ analysis }) {
  const [viewMode, setViewMode] = useState("win");

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

      <div className="fight-list">
        {fights.map((fight) => (
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
