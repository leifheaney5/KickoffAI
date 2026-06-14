// Screen 1 — Live Dashboard
const { useState: useStateDash } = React;

function Scoreboard() {
  const D = window.KP_DATA;
  return (
    <Panel className="scoreboard">
      <div className="sb-side sb-home">
        <div className="sb-team">{D.HOME.name}</div>
        <div className="sb-score mono">{D.HOME.score}</div>
      </div>
      <div className="sb-center">
        <div className="sb-half">2ND HALF</div>
        <div className="sb-clock mono">67:12</div>
        <div className="possession">
          <div className="poss-fill" style={{ width: "58%" }} />
          <span className="poss-l mono">58%</span>
          <span className="poss-r mono">42%</span>
        </div>
      </div>
      <div className="sb-side sb-away">
        <div className="sb-team">{D.AWAY.name}</div>
        <div className="sb-score mono">{D.AWAY.score}</div>
      </div>
    </Panel>
  );
}

function ControlBar() {
  const [rec, setRec] = useStateDash(true);
  return (
    <div className="control-bar">
      <Btn kind="primary">Start</Btn>
      <Btn kind="ghost">Pause</Btn>
      <Btn kind="ghost">Half</Btn>
      <Btn kind="ghost">Reset</Btn>
      <div className="control-spacer" />
      <Btn kind={rec ? "live" : "ghost"} onClick={() => setRec(!rec)}>
        <span className={"rec-dot" + (rec ? " pulse" : "")} />
        {rec ? "Recording" : "Resume Rec"}
      </Btn>
    </div>
  );
}

function DivergingRow({ row }) {
  const max = Math.max(row.home, row.away) || 1;
  const hp = (row.home / max) * 100;
  const ap = (row.away / max) * 100;
  const u = row.unit || "";
  return (
    <div className="cmp-row">
      <div className="cmp-val mono home">{row.home}{u}</div>
      <div className="cmp-bars">
        <div className="cmp-left"><div className="cmp-fill home" style={{ width: hp + "%" }} /></div>
        <div className="cmp-mid">{row.label}</div>
        <div className="cmp-right"><div className="cmp-fill away" style={{ width: ap + "%" }} /></div>
      </div>
      <div className="cmp-val mono away">{row.away}{u}</div>
    </div>
  );
}

function TeamComparison() {
  const D = window.KP_DATA;
  return (
    <Panel className="cmp">
      <SectionLabel kicker="ANALYSIS" title="Team Comparison" />
      <div className="cmp-legend">
        <span><i className="dot home" />{D.HOME.name}</span>
        <span>{D.AWAY.name}<i className="dot away" /></span>
      </div>
      <div className="cmp-rows">
        {D.COMPARE.map((r, i) => <DivergingRow key={i} row={r} />)}
      </div>
    </Panel>
  );
}

function LiveFeed() {
  const D = window.KP_DATA;
  return (
    <Panel className="feed">
      <SectionLabel kicker="REAL-TIME" title="Live Feed"
        right={<StatusChip dot="var(--c-live)" label="20 events" live />} />
      <div className="feed-list">
        {D.EVENTS.map((e, i) => (
          <div className="feed-item" key={i}>
            <EventBadge type={e.type} team={e.team} />
            <div className="feed-body">
              <div className="feed-meta">
                <TeamChip team={e.team} />
                <span className="feed-type">{D.TYPES[e.type].label}</span>
                <span className="feed-time mono">{e.t}</span>
              </div>
              <div className="feed-desc">{e.player !== "—" && <b>{e.player} · </b>}{e.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function PlayerTable() {
  const D = window.KP_DATA;
  const [sort, setSort] = useStateDash("sh");
  const cols = [
    { k: "g", label: "G" }, { k: "sh", label: "Shots" }, { k: "ot", label: "On Tgt" },
    { k: "ps", label: "Passes" }, { k: "pp", label: "Pass %" },
  ];
  const rows = [...D.PLAYERS].sort((a, b) => b[sort] - a[sort]);
  return (
    <Panel className="ptable">
      <SectionLabel kicker="PLAYERS" title="Player Stats" right={<span className="hint">click a column to sort</span>} />
      <table>
        <thead>
          <tr>
            <th className="th-name">Player</th>
            <th className="th-team">Team</th>
            {cols.map(c => (
              <th key={c.k} className={"th-num" + (sort === c.k ? " sorted" : "")} onClick={() => setSort(c.k)}>
                {c.label}{sort === c.k ? " ▾" : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => (
            <tr key={i}>
              <td className="td-name">{p.name}</td>
              <td><TeamChip team={p.team} /></td>
              {cols.map(c => <td key={c.k} className={"mono td-num" + (sort === c.k ? " sorted" : "")}>{p[c.k]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Expander({ title, count, children, open: openInit }) {
  const [open, setOpen] = useStateDash(!!openInit);
  return (
    <Panel className={"expander" + (open ? " open" : "")}>
      <button className="exp-head" onClick={() => setOpen(!open)}>
        <span className="exp-caret">{open ? "▾" : "▸"}</span>
        <span className="exp-title">{title}</span>
        {count != null && <span className="exp-count">{count}</span>}
      </button>
      {open && <div className="exp-body">{children}</div>}
    </Panel>
  );
}

function Dashboard({ t }) {
  const D = window.KP_DATA;
  const layout = t.dashLayout || "split";
  const cmp = <TeamComparison />;
  const feed = <LiveFeed />;
  let twoCol;
  if (layout === "stacked") {
    twoCol = <div className="dash-stack">{cmp}{feed}</div>;
  } else if (layout === "feed") {
    twoCol = <div className="dash-2col feed-major">{feed}{cmp}</div>;
  } else {
    twoCol = <div className="dash-2col">{cmp}{feed}</div>;
  }
  return (
    <div className="screen dash">
      <div className="dash-titlebar">
        <div className="match-title">
          <span className="mt-edit">✎</span>
          <input className="mt-input" defaultValue="Arsenal vs Chelsea — Matchday 31" />
        </div>
        <div className="status-row">
          <StatusChip dot="var(--c-live)" label="Recording" live />
          <StatusChip label="Session" value="01:12:40" />
          <StatusChip label="Events" value="20" />
          <StatusChip label="Heard" value="“Saka with the finish…”" />
        </div>
      </div>

      <Scoreboard />
      <ControlBar />
      {twoCol}
      <PlayerTable />

      <div className="exp-group">
        <Expander title="Substitutions" count={D.SUBS.length}>
          <div className="subs-list">
            {D.SUBS.map((s, i) => (
              <div className="sub-row" key={i}>
                <span className="mono sub-time">{s.t}</span>
                <TeamChip team={s.team} />
                <span className="sub-off">▼ {s.off}</span>
                <span className="sub-on">▲ {s.on}</span>
              </div>
            ))}
          </div>
        </Expander>
        <Expander title="Raw Event Log" count={D.EVENTS.length}>
          <div className="rawlog">
            {D.EVENTS.map((e, i) => (
              <div className="raw-line mono" key={i}>
                <span className="raw-t">{e.t}</span>
                <span className="raw-ty">[{D.TYPES[e.type].label}]</span>
                <span className="raw-pl">{e.player}</span>
                <span className="raw-d">{e.desc}</span>
              </div>
            ))}
          </div>
        </Expander>
        <Expander title="Post-Match Summary + Export">
          <div className="pm-summary">
            <p>Match summary will generate at full time. Export current data:</p>
            <div className="pm-actions">
              <Btn kind="primary">Export CSV</Btn>
              <Btn kind="ghost">Export JSON</Btn>
              <Btn kind="ghost">Download PNG</Btn>
            </div>
          </div>
        </Expander>
      </div>
    </div>
  );
}

window.Dashboard = Dashboard;
