// Kickoff Pulse — app shell, navigation, routing, tweaks
const { useState: useStateApp } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "fidelity": "Mid",
  "density": "Regular",
  "navPattern": "Top tabs",
  "dashLayout": "split"
}/*EDITMODE-END*/;

const NAV = [
  { id: "dash", label: "Live Dashboard", icon: "▮" },
  { id: "timeline", label: "Timeline", icon: "│" },
  { id: "insights", label: "Insights", icon: "◇" },
];

function Logo({ small }) {
  return (
    <div className={"logo" + (small ? " logo-sm" : "")}>
      <img src="assets/kp-mark.png" alt="" className="logo-mark" />
      <span className="logo-word"><b>Kickoff</b> Pulse</span>
    </div>
  );
}

function TopNav({ route, setRoute }) {
  return (
    <header className="topnav">
      <Logo />
      <nav className="topnav-tabs">
        {NAV.map(n => (
          <button key={n.id} className={"tab" + (route === n.id ? " active" : "")}
            onClick={() => setRoute(n.id)}>{n.label}</button>
        ))}
      </nav>
      <div className="topnav-right">
        <StatusChip dot="var(--c-live)" label="LIVE" live />
        <span className="np-avatar mono">KP</span>
      </div>
    </header>
  );
}

function SideNav({ route, setRoute }) {
  return (
    <aside className="sidenav">
      <Logo />
      <nav className="sidenav-list">
        {NAV.map(n => (
          <button key={n.id} className={"side-item" + (route === n.id ? " active" : "")}
            onClick={() => setRoute(n.id)}>
            <span className="side-ic">{n.icon}</span>{n.label}
          </button>
        ))}
      </nav>
      <div className="sidenav-foot">
        <StatusChip dot="var(--c-live)" label="LIVE" live />
        <span className="sidenav-build mono">100% local · v1.0</span>
      </div>
    </aside>
  );
}

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [route, setRoute] = useStateApp("dash");

  // reflect tweaks on root
  const fi = (t.fidelity || "Mid").toLowerCase();
  const dn = (t.density || "Regular").toLowerCase();

  React.useEffect(() => {
    document.documentElement.setAttribute("data-fi", fi);
    document.documentElement.setAttribute("data-density", dn);
  }, [fi, dn]);

  const sidebar = t.navPattern === "Sidebar";

  let screen;
  if (route === "dash") screen = <Dashboard t={t} />;
  else if (route === "timeline") screen = <Timeline t={t} />;
  else screen = <Insights t={t} />;

  return (
    <div className={"app" + (sidebar ? " has-side" : " has-top")} data-fi={fi} data-density={dn}>
      {sidebar ? <SideNav route={route} setRoute={setRoute} /> : <TopNav route={route} setRoute={setRoute} />}
      <main className="content">
        <div className="content-inner">{screen}</div>
      </main>

      <TweaksPanel>
        <TweakSection label="Fidelity" />
        <TweakRadio label="Look" value={t.fidelity} options={["Sketch", "Mid", "Styled"]}
          onChange={v => setTweak("fidelity", v)} />
        <TweakSection label="Layout" />
        <TweakRadio label="Density" value={t.density} options={["Compact", "Regular", "Breathable"]}
          onChange={v => setTweak("density", v)} />
        <TweakRadio label="Navigation" value={t.navPattern} options={["Top tabs", "Sidebar"]}
          onChange={v => setTweak("navPattern", v)} />
        <TweakSelect label="Dashboard layout" value={t.dashLayout}
          options={[
            { value: "split", label: "Comparison left · Feed right" },
            { value: "feed", label: "Feed left · Comparison right" },
            { value: "stacked", label: "Stacked full-width" },
          ]}
          onChange={v => setTweak("dashLayout", v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
