// Mock match data for Kickoff Pulse wireframes
window.KP_DATA = (function () {
  const HOME = { name: "Arsenal", short: "ARS", score: 2 };
  const AWAY = { name: "Chelsea", short: "CHE", score: 1 };

  // Event types -> color + glyph key
  const TYPES = {
    goal:     { label: "Goal",      color: "var(--c-live)",  glyph: "goal" },
    shot:     { label: "Shot",      color: "var(--c-signal)", glyph: "shot" },
    ontarget: { label: "On Target", color: "var(--c-cyan)",  glyph: "target" },
    save:     { label: "Save",      color: "var(--c-home2)", glyph: "save" },
    card:     { label: "Card",      color: "#E5B83B",        glyph: "card" },
    foul:     { label: "Foul",      color: "var(--c-subtle)", glyph: "foul" },
    sub:      { label: "Sub",       color: "var(--c-home2)", glyph: "sub" },
    corner:   { label: "Corner",    color: "var(--c-signal)", glyph: "corner" },
  };

  // Live feed events (most recent first)
  const EVENTS = [
    { t: "67:12", type: "goal",     team: "home", player: "Saka",      desc: "Goal! Right-foot finish from the edge of the box." },
    { t: "65:48", type: "shot",     team: "away", player: "Palmer",    desc: "Curling effort drifts just wide of the far post." },
    { t: "63:30", type: "card",     team: "away", player: "Caicedo",   desc: "Yellow card for a tactical foul in midfield." },
    { t: "61:05", type: "save",     team: "home", player: "Raya",      desc: "Low save to keep the lead intact." },
    { t: "58:22", type: "ontarget", team: "home", player: "Ødegaard",  desc: "Driven shot forces a parry from the keeper." },
    { t: "55:40", type: "corner",   team: "away", player: "—",         desc: "Corner won on the left flank." },
    { t: "52:18", type: "foul",     team: "home", player: "Rice",      desc: "Foul conceded just outside the centre circle." },
    { t: "49:03", type: "shot",     team: "home", player: "Martinelli",desc: "Half-volley deflected behind for a corner." },
    { t: "47:55", type: "sub",      team: "away", player: "Jackson",   desc: "Substitution — fresh legs up top." },
    { t: "46:00", type: "goal",     team: "away", player: "Palmer",    desc: "Penalty converted, low to the left corner." },
    { t: "45:00", type: "ontarget", team: "away", player: "Sterling",  desc: "Snapshot held comfortably by the keeper." },
    { t: "41:27", type: "save",     team: "home", player: "Raya",      desc: "Strong hand to deny the near-post effort." },
    { t: "38:14", type: "card",     team: "home", player: "Partey",    desc: "Yellow for a late challenge." },
    { t: "33:51", type: "shot",     team: "away", player: "Madueke",   desc: "Drilled across goal, no one gambling." },
    { t: "28:09", type: "goal",     team: "home", player: "Jesus",     desc: "Goal! Tap-in from a low cross." },
    { t: "24:36", type: "ontarget", team: "home", player: "Saka",      desc: "Stinging drive tipped over the bar." },
    { t: "19:42", type: "corner",   team: "home", player: "—",         desc: "Corner from a blocked shot." },
    { t: "14:18", type: "foul",     team: "away", player: "Cucurella", desc: "Foul on the touchline." },
    { t: "08:55", type: "shot",     team: "home", player: "Ødegaard",  desc: "Early effort skips wide." },
    { t: "02:30", type: "ontarget", team: "away", player: "Palmer",    desc: "First sight of goal, straight at the keeper." },
  ];

  // Team comparison stats
  const COMPARE = [
    { label: "Goals",     home: 2,  away: 1  },
    { label: "Shots",     home: 11, away: 7  },
    { label: "On Target", home: 6,  away: 3  },
    { label: "Passes",    home: 421,away: 388 },
    { label: "Pass %",    home: 87, away: 82, unit: "%" },
  ];

  // Player stats
  const PLAYERS = [
    { name: "Bukayo Saka",     team: "home", g: 1, sh: 4, ot: 2, ps: 52,  pp: 89 },
    { name: "Martin Ødegaard", team: "home", g: 0, sh: 3, ot: 1, ps: 71,  pp: 91 },
    { name: "Gabriel Jesus",   team: "home", g: 1, sh: 2, ot: 2, ps: 28,  pp: 82 },
    { name: "Declan Rice",     team: "home", g: 0, sh: 1, ot: 0, ps: 66,  pp: 90 },
    { name: "Gabriel Martinelli", team: "home", g: 0, sh: 2, ot: 1, ps: 31, pp: 84 },
    { name: "Cole Palmer",     team: "away", g: 1, sh: 3, ot: 1, ps: 44,  pp: 85 },
    { name: "Nicolas Jackson", team: "away", g: 0, sh: 2, ot: 1, ps: 19,  pp: 78 },
    { name: "Enzo Fernández",  team: "away", g: 0, sh: 1, ot: 0, ps: 58,  pp: 88 },
    { name: "Raheem Sterling", team: "away", g: 0, sh: 1, ot: 1, ps: 33,  pp: 80 },
  ];

  const SUBS = [
    { t: "47:55", team: "away", off: "Mudryk", on: "Madueke" },
    { t: "62:10", team: "home", off: "Jesus",  on: "Trossard" },
  ];

  // Momentum series: minute -> value (-100 away pressure .. +100 home pressure)
  const MOMENTUM = [];
  (function () {
    const pts = [0, 10, 25, -15, -40, 5, 30, 55, 20, -10, -55, -35, 10, 45, 60, 40, 25, 50, 35, 20];
    for (let i = 0; i < pts.length; i++) {
      MOMENTUM.push({ min: i * 3.5, v: pts[i] });
    }
  })();

  const HEADLINE = [
    { label: "Shots",        home: 11, away: 7,  fmt: "vs" },
    { label: "On Target",    home: 6,  away: 3,  fmt: "vs" },
    { label: "Conversion %", home: 18, away: 14, fmt: "vs", unit: "%" },
    { label: "Momentum",     leader: "Arsenal",  fmt: "leader" },
  ];

  return { HOME, AWAY, TYPES, EVENTS, COMPARE, PLAYERS, SUBS, MOMENTUM, HEADLINE };
})();
