// Shared UI primitives for Kickoff Pulse wireframes
const { useState } = React;

// ---- Simple geometric event glyphs (no illustration, just primitives) ----
function Glyph({ kind, size = 16 }) {
  const s = size;
  const stroke = "rgba(255,255,255,0.92)";
  const common = { width: s, height: s, viewBox: "0 0 24 24", fill: "none" };
  switch (kind) {
    case "goal": // filled circle (ball)
      return (<svg {...common}><circle cx="12" cy="12" r="7" fill={stroke} /></svg>);
    case "shot": // arrow-ish chevron
      return (<svg {...common}><path d="M6 6l10 6-10 6" stroke={stroke} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></svg>);
    case "target": // ring + dot
      return (<svg {...common}><circle cx="12" cy="12" r="6.5" stroke={stroke} strokeWidth="2"/><circle cx="12" cy="12" r="2" fill={stroke}/></svg>);
    case "save": // open glove ~ arc
      return (<svg {...common}><path d="M5 13a7 7 0 0 1 14 0" stroke={stroke} strokeWidth="2.2" strokeLinecap="round"/><rect x="9" y="13" width="6" height="5" rx="1.5" stroke={stroke} strokeWidth="2"/></svg>);
    case "card": // rounded rect
      return (<svg {...common}><rect x="8" y="5" width="8" height="14" rx="1.6" fill={stroke}/></svg>);
    case "foul": // X
      return (<svg {...common}><path d="M7 7l10 10M17 7L7 17" stroke={stroke} strokeWidth="2.4" strokeLinecap="round"/></svg>);
    case "sub": // two opposing arrows
      return (<svg {...common}><path d="M5 9h10l-3-3M19 15H9l3 3" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>);
    case "corner": // flag
      return (<svg {...common}><path d="M8 5v14" stroke={stroke} strokeWidth="2" strokeLinecap="round"/><path d="M8 6h8l-3 3 3 3H8" fill={stroke}/></svg>);
    default:
      return (<svg {...common}><circle cx="12" cy="12" r="6" stroke={stroke} strokeWidth="2"/></svg>);
  }
}

// ---- Event badge: colored circle, team-colored ring ----
function EventBadge({ type, team, size = 32 }) {
  const T = window.KP_DATA.TYPES[type];
  const ring = team === "home" ? "var(--c-home)" : "var(--c-away)";
  return (
    <span className="ev-badge" style={{
      width: size, height: size,
      background: T.color,
      boxShadow: `0 0 0 2px ${ring}`,
    }}>
      <Glyph kind={T.glyph} size={Math.round(size * 0.5)} />
    </span>
  );
}

// ---- Status chip (muted pill + colored dot) ----
function StatusChip({ dot, label, value, live }) {
  return (
    <span className={"chip" + (live ? " chip-live" : "")}>
      {dot && <span className="chip-dot" style={{ background: dot }} />}
      {label && <span className="chip-label">{label}</span>}
      {value != null && <span className="chip-val">{value}</span>}
    </span>
  );
}

function TeamChip({ team }) {
  const D = window.KP_DATA;
  const isHome = team === "home";
  return (
    <span className="team-chip" style={{
      color: isHome ? "var(--c-home2)" : "#FF6B6B",
      borderColor: isHome ? "rgba(30,123,255,.4)" : "rgba(220,38,38,.45)",
      background: isHome ? "rgba(30,123,255,.12)" : "rgba(220,38,38,.12)",
    }}>{isHome ? D.HOME.short : D.AWAY.short}</span>
  );
}

// ---- Section label: accent left-border + small label chip + title ----
function SectionLabel({ kicker, title, right }) {
  return (
    <div className="section-label">
      <div className="section-label-l">
        <span className="section-kicker">{kicker}</span>
        <h3 className="section-title">{title}</h3>
      </div>
      {right && <div className="section-label-r">{right}</div>}
    </div>
  );
}

// ---- Panel (glass card) ----
function Panel({ children, className = "", style = {} }) {
  return <section className={"panel " + className} style={style}>{children}</section>;
}

// ---- Button ----
function Btn({ children, kind = "ghost", icon, onClick, active }) {
  return (
    <button className={`btn btn-${kind}${active ? " is-active" : ""}`} onClick={onClick}>
      {icon}{children}
    </button>
  );
}

Object.assign(window, { Glyph, EventBadge, StatusChip, TeamChip, SectionLabel, Panel, Btn });
