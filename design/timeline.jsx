// Screen 2 — Match Timeline
const { useState: useStateTL } = React;

function TimelineNode({ e, idx, expanded, onToggle }) {
  const D = window.KP_DATA;
  const T = D.TYPES[e.type];
  const side = idx % 2 === 0 ? "left" : "right";
  const locations = ["Box, left", "Centre circle", "Right wing", "Edge of box", "Penalty spot", "Half-line"];
  const results = ["Scored", "Off target", "Saved", "Blocked", "Booked", "Completed"];
  return (
    <div className={"tl-node " + side}>
      <div className="tl-card" onClick={onToggle}>
        <div className="tl-card-head">
          <span className="tl-type" style={{ color: T.color }}>{T.label}</span>
          <span className="mono tl-time">{e.t}</span>
        </div>
        <div className="tl-card-desc">{e.player !== "—" && <b>{e.player} · </b>}{e.desc}</div>
        {expanded && (
          <div className="tl-detail">
            <div className="tl-detail-grid">
              <div><span className="k">Player</span><span className="v">{e.player}</span></div>
              <div><span className="k">Team</span><span className="v"><TeamChip team={e.team} /></span></div>
              <div><span className="k">Location</span><span className="v">{locations[idx % locations.length]}</span></div>
              <div><span className="k">Result</span><span className="v">{results[idx % results.length]}</span></div>
              <div><span className="k">Match Time</span><span className="v mono">{e.t}</span></div>
            </div>
          </div>
        )}
      </div>
      <div className="tl-axis">
        <span className="tl-badge"><EventBadge type={e.type} team={e.team} size={36} /></span>
      </div>
    </div>
  );
}

function Timeline({ t }) {
  const D = window.KP_DATA;
  const [filter, setFilter] = useStateTL("all");
  const [asc, setAsc] = useStateTL(false);
  const [openIdx, setOpenIdx] = useStateTL(0);

  let list = D.EVENTS.map((e, i) => ({ ...e, _i: i }));
  if (filter !== "all") list = list.filter(e => e.type === filter);
  list = [...list].sort((a, b) => {
    const av = a.t, bv = b.t;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  });

  return (
    <div className="screen timeline">
      <div className="page-head">
        <div>
          <span className="page-kicker">MATCH</span>
          <h2 className="page-title">Timeline</h2>
        </div>
      </div>

      <div className="tl-filterbar">
        <label className="field">
          <span className="field-label">Event type</span>
          <select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="all">All events</option>
            {Object.keys(D.TYPES).map(k => <option key={k} value={k}>{D.TYPES[k].label}</option>)}
          </select>
        </label>
        <button className="sort-toggle" onClick={() => setAsc(!asc)}>
          Sort: {asc ? "Earliest first ↑" : "Latest first ↓"}
        </button>
        <span className="hint">click any card to expand details</span>
      </div>

      <div className="tl-rail">
        <div className="tl-line" />
        {list.map((e, i) => (
          <TimelineNode key={e._i} e={e} idx={i}
            expanded={openIdx === e._i}
            onToggle={() => setOpenIdx(openIdx === e._i ? -1 : e._i)} />
        ))}
      </div>

      <div className="tl-export">
        <Btn kind="primary">⤓ Export Timeline as PNG</Btn>
      </div>
    </div>
  );
}

window.Timeline = Timeline;
