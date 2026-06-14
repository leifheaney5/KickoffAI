# Handoff: Kickoff Pulse — AI Soccer Match Intelligence Platform

## Overview

**Kickoff Pulse** is an AI-powered, 100% local soccer match intelligence platform. Users narrate match events by voice; the app transcribes, parses, and displays live stats in real time. This handoff covers the **three core screens** of the desktop-first web application (Streamlit-based, dark sports-tech aesthetic).

The design explores structure and flow through an **interactive HTML prototype** showing all three connected screens with navigation, data visualization, and interactive components.

## About the Design Files

The files bundled here are **design references created in HTML/React** — functional prototypes showing intended layout, interaction, and visual direction. These are **not production code to copy directly**, but rather:

- A clickable, fully-interactive prototype you can navigate and test
- Reference implementations of UI patterns, layout systems, and component behavior
- Design tokens and styling approach (dark HUD aesthetic, glass morphism, sports-tech typography)

**Your task**: Implement these designs in your **target environment** (Python Streamlit, React app, native, etc.) using:
- Your existing framework and component libraries
- Established design system and patterns in your codebase
- The layout, interaction patterns, and visual direction shown in the prototype as a guide

If no framework exists yet, this prototype demonstrates a React-based approach suitable for a modern, interactive dashboard.

## Fidelity

**Mid-fidelity with style variations** (Sketch ↔ Mid ↔ Styled):
- The prototype is **structured and layout-complete** with realistic data and interactions
- Typography, color, spacing, and components follow the Kickoff Pulse brand guide
- Three **visual fidelity modes** are baked in (toggle via Tweaks panel) to explore rough wireframe vs. polished UI — use the "Mid" or "Styled" mode as your target
- Implement the layouts and interactions pixel-precisely using your codebase's tools; adapt colors/fonts to match your design system

## Screens / Views

### Screen 1: Live Dashboard (Hero Screen)

**Purpose**: Real-time match intelligence center. Users monitor live score, team stats, event feed, and player performance during a match.

**Layout**:
- Full-width, max-width 1240px container with 24px padding
- Sticky top bar with editable match title (left), status chips row (center-right)
- Hero scoreboard: 3-column grid (Home team | Center clock + half label + possession bar | Away team)
  - Home/Away: team name (16px), large score (68px mono), centered
  - Center: "2ND HALF" label (11px, mono), clock (46px, mono, glowing), possession bar (7px height, blue-left / red-right)
- Control bar: flex row with Start/Pause/Half/Reset buttons, spacer, Recording button (pulsing live dot)
- Two-column section (1fr 1fr grid, gap 16px):
  - **Left**: Team Comparison panel
    - Legend (Arsenal / Chelsea with color dots)
    - 5 stat rows (Goals, Shots, On Target, Passes, Pass %)
    - Each row: diverging bar chart (blue left, red right, centered label)
  - **Right**: Live Feed panel
    - Scrollable card list (max-height 430px, overflow-y auto)
    - 20 recent events, newest first
    - Each card: event badge (32px circle, colored icon, team-colored ring) | body (type chip, team chip, time, description with player name bold)
- Full-width player stats table below
  - Columns: Player, Team, G, Shots, On Tgt, Passes, Pass %
  - Sortable (click column header to sort, ▾ indicates active sort)
  - Rows highlight on hover
- Three collapsible expanders at bottom (collapsed by default):
  - **Substitutions**: 2 rows, each with time, team chip, off player (red ▼), on player (blue ▲)
  - **Raw Event Log**: monospace, dense 4-column grid (time | type | player | description), scrollable
  - **Post-Match Summary + Export**: text + 3 export buttons (CSV, JSON, PNG)

**Colors**:
- Home team: `#1E7BFF` (Pulse Blue) for bars, `#4DA3FF` (Signal Blue) for text
- Away team: `#DC2626` (Signal Red)
- Accents: `#FF3D6E` (Hot Pink for live/recording), `#2BE7FF` (Cyan)
- Background: deep navy gradient (#080b16 → #0b1126)
- Panels: glass morphism (rgba(255,255,255,0.055) + 12px blur)
- Text: #EAF1FF (soft white-blue), #9FB6DD (muted), #7E95BF (subtle)

**Typography**:
- Display/headings: Chakra Petch (600, 700 weight) — geometric, squared, techno-sport
- Body: Sora (400, 500, 600) — clean, humanist
- Monospace (stats, clock, mono text): Spline Sans Mono — tabular numerals
- Sizes: 68px (score), 46px (clock), 18px (section titles), 15px (body), 11px (labels)

**Components**:
- **Status Chip**: 12px pill, muted background, colored dot, label, optional value. Live variant animates the dot (pulse 1.6s).
- **Event Badge**: 32px circle, event-type color fill, team-colored 2px ring, white glyph inside
- **Team Chip**: 10px pill, team color border + light fill, uppercase team abbrev (ARS/CHE), font-weight 700
- **Button**: 12.5px uppercase, display: flex gap 8px, padding 9px 16px, rounded 9px
  - Ghost (default): rgba(255,255,255,0.04) bg, muted text, hover brightens
  - Primary: gradient (Pulse Blue → #1462d6), white text, glow shadow (0 6px 16px rgba(30,123,255,.3))
  - Live: rgba(255,61,110,.16) bg, live pink border
- **Section Label**: left border (3px, Pulse Blue) + title. Left-align in a .section-label-l div with 11px left padding.
- **Panel**: rounded 12px, glass background, 1px subtle border, subtle shadow

**Interactive States**:
- Editable match title: edit icon (✎) next to input; input shows bottom border only on hover/focus
- Recording button: pulsing red dot (animation 1.6s)
- Status chips (live): dot has box-shadow pulse animation
- Table rows: hover background (rgba(255,255,255,.03))
- Expander buttons: click to toggle open/closed; caret rotates (▸/▾)

**Data**:
- Match: Arsenal 2–1 Chelsea, 2nd half, 67:12 elapsed
- 20 live events in feed (goals, shots, saves, cards, fouls, subs, corners)
- 9 player stats rows (5 Arsenal, 4 Chelsea)
- 2 substitutions

**Layout Variations** (controlled by Tweaks panel):
1. **Split** (default): Comparison left, Feed right (1fr 1fr)
2. **Feed-major**: Feed left, Comparison right
3. **Stacked**: Full-width, Comparison then Feed vertically

---

### Screen 2: Match Timeline

**Purpose**: Chronological view of all match events. Users filter by event type, sort ascending/descending, and click to expand detailed information.

**Layout**:
- Page header (MATCH / Timeline title with gradient text)
- Filter bar: event type dropdown (All events / Goal / Shot / On Target / Save / Card / Foul / Sub / Corner), sort toggle (Latest first ↓ / Earliest first ↑), hint text "click any card to expand details"
- Vertical centered timeline rail:
  - Central vertical line (2px, linear gradient fade at top/bottom)
  - Alternating left/right event cards (layout: left-card | center-badge | right-card alternates)
  - Each card:
    - Header: event type (colored, uppercase, 13px, Chakra Petch bold) | time (mono, 12px, muted, right-aligned)
    - Description: 13px, player name bold, match context
    - On click, expands to show detail panel:
      - 2×3 grid of metadata: Player | Team | Location | Result | Match Time
      - Left-aligned for right-side cards, right-aligned for left-side cards
  - Badge: 36px event circle, centered on rail, team-colored ring, 4px offset shadow
  - Card styling: glass bg, subtle border, rounded 12px, hover slightly lifts and brightens border
- Export button at bottom: "⤓ Export Timeline as PNG"

**Colors**: Same palette as Dashboard; event badges use event-type-specific colors (Goal = Hot Pink, Shot = Signal Blue, Card = Yellow, etc.)

**Data**: 20 events with varied types, teams, players, times

**Interactive**:
- Click event card to toggle detail expansion
- Change filter dropdown to re-render list (filtered)
- Toggle sort order to reverse list

---

### Screen 3: Insights

**Purpose**: Match analysis and AI-powered recommendations. Users view momentum trends, headline stats, and interact with an AI assistant for tactical insights.

**Layout**:
- Page header (ANALYSIS / Insights title)
- **Momentum Graph** panel
  - Full-width area chart (SVG, 1000×260px)
  - X-axis: match minutes (0' to FT)
  - Y-axis: pressure (-100 away bottom to +100 home top), centered neutral line
  - Blue fill + stroke above center (home pressure), red fill + stroke below (away pressure)
  - Gradient fills fade to transparent at top/bottom
  - Axis labels: 0', 15', 30', 45', 60', FT
- **Headline Stats** row: 4 chips in a grid (repeat 4, 1fr each), gap 16px
  - Each chip shows: label (10px mono, uppercase) | vs-display (two bold numbers + "vs" label) or leader-display (team name in Signal Blue)
  - Example: "Shots: 11 vs 7", "Momentum: Arsenal"
- **AI Match Analyst** panel
  - Quick-prompt buttons: 4 pills (Who's on top? / What should the trailing team do? / Key player so far? / Predict the next goal)
  - Chat stream: messages in bubbles
    - AI: left-align, glass bg, dark, bordered, small "PULSE AI" tag above
    - User: right-align, gradient bg (Pulse Blue), white text, rounded except bottom-right corner (4px)
    - Max-height 340px, scrollable, monospace sender tags (9px)
  - Input: flex row, input field (glass bg, rounded, focuses to home-blue border) + Send button (primary blue)

**Data**:
- Momentum: 20 data points across 70 match minutes, oscillating pressure
- Headlines: Shots, On Target, Conversion %, Momentum Leader
- Chat: 3 seed messages (AI analysis → user question → AI response)

---

## Interactions & Behavior

### Navigation
- **Top tabs** (default): three clickable tabs (Live Dashboard, Timeline, Insights) at top. Active tab highlighted with blue background + border.
- **Sidebar** (variant): left rail with logo, nav list, footer badges. Same behavior, different layout.
- Clicking a tab updates the visible screen instantly.

### Dashboard
- **Match title**: editable input. Click ✎ icon or input itself to focus. Border appears on focus/hover.
- **Recording button**: 
  - Pulsing red dot (box-shadow animation 1.6s, pulse keyframe)
  - Click toggles recording state (button text changes, dot stops pulsing when paused)
- **Team Comparison bars**: diverging layout, bars grow toward center label. Smooth if data updates.
- **Live Feed scroll**: CSS overflow-y auto, scrollbar styled (10px width, rounded thumb at rgba(255,255,255,.12))
- **Player table**: click any column header to sort by that column. Re-render rows sorted. Active sort column shows ▾ and highlight.
- **Expanders**: 
  - Click header to toggle open/closed state
  - Caret rotates (▸ → ▾)
  - Body slides in/out (no animation in wireframe, but add CSS transition in implementation)
  - Count badge shows item count

### Timeline
- **Event filter**: dropdown changes filter state, list re-renders instantly
- **Sort toggle**: click to flip asc/desc, re-sort list
- **Event cards**: click card to toggle detail panel. Only one card expanded at a time (optional: allow multiple).
- **Detail panel**: appears below card content on click, shows 2-col metadata grid

### Insights
- **Quick prompts**: click any prompt button to send that message. Adds user bubble + AI response bubble to chat stream.
- **Chat input**: type text, press Enter or click Send to submit. Input clears after send. New messages appear in stream.
- **Momentum chart**: static SVG, no interaction (but in production, could add hover tooltip with minute + pressure value)

### Tweaks Panel (In-Design Controls)

Located top-right, accessible via **Tweaks** toggle in the toolbar:

- **Fidelity**: Radio (Sketch / Mid / Styled)
  - Sketch: hand-drawn font (Architects Daughter), dashed borders, desaturated colors, wireframe aesthetic
  - Mid: flat glass (no blur), colors + structure intact
  - Styled: full HUD (blur, shadows, gradient, glow) — production look
- **Density**: Radio (Compact / Regular / Breathable)
  - Compact: `--gap:10px`, `--pad:14px`, `--fs:14px`
  - Regular: `--gap:16px`, `--pad:20px`, `--fs:15px` (default)
  - Breathable: `--gap:26px`, `--pad:30px`, `--fs:16px`
- **Navigation**: Radio (Top tabs / Sidebar)
  - Top tabs: `.app.has-top` layout, sticky header
  - Sidebar: `.app.has-side` grid layout (248px sidebar + 1fr content)
- **Dashboard layout**: Select (Comparison-left, Feed-left, Stacked)
  - Affects the 2-col section below scoreboard

These tweaks persist in localStorage and reflect immediately on root element attributes (`data-fi`, `data-density`) and React state.

---

## State Management

### Dashboard
- `route`: string (dash / timeline / insights) — which screen is active
- `fidelity`, `density`, `navPattern`, `dashLayout`: tweak state (persisted via useTweaks)
- `rec`: boolean — recording button state (mock, no real recording)
- `sort`: string (column key) — player table sort column
- `open`: per-expander boolean — which expanders are expanded (local component state)

### Timeline
- `filter`: string (all / goal / shot / etc.) — event type filter
- `asc`: boolean — sort ascending (false = latest first)
- `openIdx`: number — which event card is expanded (-1 = none)

### Insights
- `msgs`: array of { who: "ai" | "user", text: string } — chat messages
- `draft`: string — current input text

### Global (window.KP_DATA)
- Match: HOME { name, short, score }, AWAY
- TYPES: event type → { label, color, glyph }
- EVENTS: 20 event objects with t, type, team, player, desc
- COMPARE: 5 stat rows with home, away, label, unit
- PLAYERS: 9 player rows with name, team, stats
- SUBS: 2 substitution events
- MOMENTUM: 20 points with min, v (value -100 to +100)
- HEADLINE: 4 stat chips

---

## Design Tokens

### Colors (CSS variables)
```css
--c-bg1: #080b16          /* Deep navy-black 1 */
--c-bg2: #0b1126          /* Deep navy-black 2 (gradient) */
--c-home: #1E7BFF         /* Pulse Blue — home team, primary accent */
--c-home2: #4DA3FF        /* Signal Blue — home hover/secondary */
--c-away: #DC2626         /* Signal Red — away team */
--c-live: #FF3D6E         /* Hot Pink — live/recording indicator */
--c-cyan: #2BE7FF         /* Cyan — accent, AI tag */
--c-signal: #4DA3FF       /* Signal Blue (same as home2) */
--c-text: #EAF1FF         /* Soft white-blue — primary text */
--c-muted: #9FB6DD        /* Blue-gray — secondary text */
--c-subtle: #7E95BF       /* Darker blue-gray — tertiary text, labels */
--panel: rgba(255,255,255,0.055)    /* Glass morphism base */
--panel-2: rgba(255,255,255,0.03)   /* Slightly darker glass */
--border: rgba(255,255,255,0.08)    /* Subtle 1px border */
--border-2: rgba(255,255,255,0.12)  /* Slightly brighter border */
```

### Spacing (CSS variables, density-dependent)
```css
/* Regular (default) */
--gap: 16px              /* Major section gaps */
--pad: 20px              /* Panel/container padding */
--rowgap: 10px           /* Inter-row spacing (stats, feed items) */

/* Compact variant */
--gap: 10px; --pad: 14px; --rowgap: 6px

/* Breathable variant */
--gap: 26px; --pad: 30px; --rowgap: 16px
```

### Typography
- **Display**: Chakra Petch, weights 500/600/700, letter-spacing .01–.06em
  - 30px: page titles (h1)
  - 22px: titles (h2)
  - 18px: section titles (h3)
  - 14px: nav labels, button text (h4)
  - 13px: event types, subsection labels (h5)
  - 11px: kicker labels, abbreviations (h6)
- **Body**: Sora, weights 400/500/600
  - 15px: default body text (regular)
  - 13px: secondary text (feed descriptions, card body)
  - 12px: tertiary (hints, small labels)
  - 11px: micro (chips, monospace labels)
- **Monospace**: Spline Sans Mono, weights 400/500/600 (tabular numerals)
  - 46px: match clock
  - 26px: stats (headline chips)
  - 14px: player table, raw log
  - 12px: timestamps, pass %
  - 11px: labels, small text

### Border Radius
- 99px: pills (chips, buttons)
- 12px: default panels, cards, inputs
- 10px: nav items, smaller cards
- 9px: buttons, icon buttons
- 8px: select dropdowns, input fields
- 6px: team chips, small elements
- 4px: timeline detail panel (accent corner)

### Shadows
- Panel: `0 10px 30px rgba(0,0,0,.35)` (default)
- Button primary: `0 6px 16px rgba(30,123,255,.3)` (blue glow)
- Badge: `0 0 0 2px {team-color}` (team-colored ring)
- Timeline badge: `0 0 0 2px var(--c-bg2), 0 0 0 4px rgba(255,255,255,.1)` (double ring)

### Animations
- **Pulse (dot)**: 1.6s infinite, box-shadow expands then fades
- **Hover transitions**: all .18s–.2s (color, bg, border, transform)
- Lift on hover: `transform: translateY(-1px)`
- No heavy animations on primary content (keep performance high for data dashboard)

---

## Assets

1. **Logo mark** (SVG or PNG):
   - `assets/kp-mark.png` (520×300px, transparent background)
   - Soccer ball + audio waveform visual, blue (#1E7BFF / #4DA3FF)
   - Used in nav lockup (30px height)

2. **Favicon** (optional): Kickoff Pulse logo mark

3. **Fonts** (Google Fonts, already linked):
   - Chakra Petch (500, 600, 700)
   - Sora (400, 500, 600, 700)
   - Spline Sans Mono (400, 500, 600)
   - Architects Daughter (400) — sketch mode only

---

## Files

- **Kickoff Pulse Wireframes.html** — Main prototype (all-in-one, ready to open in browser)
- **data.js** — Mock match data (teams, events, stats, players, momentum points)
- **components.jsx** — Shared UI primitives (Glyph, EventBadge, StatusChip, TeamChip, SectionLabel, Panel, Btn)
- **dashboard.jsx** — Screen 1 (Scoreboard, ControlBar, TeamComparison, LiveFeed, PlayerTable, Expander components)
- **timeline.jsx** — Screen 2 (TimelineNode, Timeline screen with filter & sort)
- **insights.jsx** — Screen 3 (MomentumGraph, HeadlineChips, AIChat screen)
- **app.jsx** — App shell, navigation, tweaks panel, routing
- **tweaks-panel.jsx** — Tweaks host protocol (useTweaks, TweaksPanel, control components)

---

## How to Implement

### Starting Point
The prototype is a **React app with mock data**. To implement:

1. **If targeting Streamlit**: Extract the layout, data flow, and interaction patterns. Rebuild using Streamlit components (st.columns, st.metric, st.chat_input, etc.). Keep the design tokens and visual direction.

2. **If targeting a web framework** (React, Vue, Angular, etc.): 
   - Use this React prototype as a direct reference
   - Adapt to your codebase's routing, state management (Redux, Zustand, Pinia, etc.)
   - Replace mock data with real match data from your backend
   - Keep the component structure and layout system

3. **Design system integration**:
   - Map colors to your existing brand/design tokens
   - Use your codebase's typography scale (this prototype uses Chakra Petch / Sora / Spline Sans Mono)
   - Adapt spacing scale to match your system (this uses CSS custom properties for easy override)

### Key Decisions
- **Real-time updates**: Replace mock EVENTS with a WebSocket or polling connection to your match data API
- **Recording**: Implement actual voice input / transcription (the prototype's recording button is a mock toggle)
- **Chat**: Wire the AI Chat input to your Claude API or LLM backend
- **Exports**: Implement CSV/JSON/PNG export for the timeline and summary data

---

## Notes for Developers

- The prototype uses **Chakra Petch** for a sports-tech, geometric feel. If unavailable in your codebase, substitute with **Inter Bold** (closer in weight) or your brand's bold geometric sans.
- **Glass morphism** (backdrop-filter: blur) is applied throughout. If targeting older browsers, fall back to solid backgrounds with increased opacity.
- The **Fidelity tweaks** (Sketch ↔ Mid ↔ Styled) are demo features showing design flexibility. In production, pick one visual direction and ship it; keep the density tweaks for accessibility/preference.
- **Sidebar navigation** is provided as a variant. The default is **top tabs**, which suits a data-heavy dashboard. Either is valid; choose based on your product needs and screen real estate.
- The **player table** and **team comparison** are static mock data. In production, wire them to real match events and compute stats on-the-fly.

---

## Questions?

This handoff is self-contained. If unclear on any layout, color, or interaction, refer to the prototype itself — it's fully clickable and shows all states.

Enjoy building! 🎯
