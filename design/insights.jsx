// Screen 3 — Insights
const { useState: useStateIns } = React;

function MomentumGraph() {
  const D = window.KP_DATA;
  const W = 1000, H = 260, cx = H / 2;
  const pts = D.MOMENTUM;
  const maxMin = pts[pts.length - 1].min;
  const xOf = m => (m / maxMin) * W;
  const yOf = v => cx - (v / 100) * (cx - 16);

  // Build smooth-ish path
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(p.min).toFixed(1)},${yOf(p.v).toFixed(1)}`).join(" ");
  const homeArea = `${line} L${W},${cx} L0,${cx} Z`;

  return (
    <Panel className="momentum">
      <SectionLabel kicker="PRESSURE" title="Momentum"
        right={<span className="hint">above = {D.HOME.name} · below = {D.AWAY.name}</span>} />
      <div className="mom-chart">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="mom-svg">
          <defs>
            <linearGradient id="homeFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(30,123,255,.55)" />
              <stop offset="100%" stopColor="rgba(30,123,255,0)" />
            </linearGradient>
            <clipPath id="aboveClip"><rect x="0" y="0" width={W} height={cx} /></clipPath>
            <clipPath id="belowClip"><rect x="0" y={cx} width={W} height={cx} /></clipPath>
          </defs>
          {/* home (above center) */}
          <g clipPath="url(#aboveClip)">
            <path d={homeArea} fill="url(#homeFill)" />
            <path d={line} fill="none" stroke="var(--c-home)" strokeWidth="2.5" />
          </g>
          {/* away (below center) */}
          <g clipPath="url(#belowClip)">
            <path d={homeArea} fill="rgba(220,38,38,.30)" />
            <path d={line} fill="none" stroke="var(--c-away)" strokeWidth="2.5" />
          </g>
          <line x1="0" y1={cx} x2={W} y2={cx} stroke="rgba(255,255,255,.35)" strokeWidth="1.5" strokeDasharray="6 5" />
        </svg>
        <div className="mom-axis">
          {[0, 15, 30, 45, 60, "FT"].map((m, i) => <span key={i} className="mono">{m === "FT" ? m : m + "'"}</span>)}
        </div>
      </div>
    </Panel>
  );
}

function HeadlineChips() {
  const D = window.KP_DATA;
  return (
    <div className="headline-row">
      {D.HEADLINE.map((h, i) => (
        <Panel className="headline-chip" key={i}>
          <span className="hc-label">{h.label}</span>
          {h.fmt === "leader"
            ? <span className="hc-leader">{h.leader}</span>
            : <span className="hc-vs">
                <b className="home">{h.home}{h.unit || ""}</b>
                <i>vs</i>
                <b className="away">{h.away}{h.unit || ""}</b>
              </span>}
        </Panel>
      ))}
    </div>
  );
}

const CHAT_SEED = [
  { who: "ai", text: "Arsenal lead 2–1 and have controlled 58% of possession. Their press has forced 6 shots on target to Chelsea's 3." },
  { who: "user", text: "Who's on top right now?" },
  { who: "ai", text: "Arsenal. Momentum has swung their way since the 55th minute — three high-danger chances and sustained territory in the final third." },
];

function AIChat() {
  const [msgs, setMsgs] = useStateIns(CHAT_SEED);
  const [draft, setDraft] = useStateIns("");
  const prompts = ["Who's on top?", "What should the trailing team do?", "Key player so far?", "Predict the next goal"];
  const send = (text) => {
    const q = (text || draft).trim();
    if (!q) return;
    setMsgs(m => [...m, { who: "user", text: q },
      { who: "ai", text: "Analyzing match context… (wireframe placeholder response — the AI analyst would respond here with a concise, data-grounded read.)" }]);
    setDraft("");
  };
  return (
    <Panel className="chat">
      <SectionLabel kicker="ASSISTANT" title="AI Match Analyst" />
      <div className="chat-prompts">
        {prompts.map((p, i) => <button key={i} className="prompt-chip" onClick={() => send(p)}>{p}</button>)}
      </div>
      <div className="chat-stream">
        {msgs.map((m, i) => (
          <div key={i} className={"bubble " + m.who}>
            {m.who === "ai" && <span className="bub-tag">PULSE AI</span>}
            <p>{m.text}</p>
          </div>
        ))}
      </div>
      <div className="chat-input">
        <input value={draft} placeholder="Ask about the match…"
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") send(); }} />
        <Btn kind="primary" onClick={() => send()}>Send</Btn>
      </div>
    </Panel>
  );
}

function Insights({ t }) {
  return (
    <div className="screen insights">
      <div className="page-head">
        <div>
          <span className="page-kicker">ANALYSIS</span>
          <h2 className="page-title">Insights</h2>
        </div>
      </div>
      <MomentumGraph />
      <HeadlineChips />
      <AIChat />
    </div>
  );
}

window.Insights = Insights;
