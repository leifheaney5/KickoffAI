#!/usr/bin/env python3
"""
Kickoff Pulse — possession and sequence reconstruction.

A possession is one team's spell of control; a sequence is a coherent passage
within it. Almost every derived metric worth having — PPDA, field tilt, sequence
directness, possessions ending in a shot, high turnovers — is defined in terms of
these rather than of individual events, so they are built before the metrics that
need them.

Deterministic by design: the same event log always yields the same possessions.
That matters because a metric whose value drifts between runs cannot be trusted,
and because the edge cases in football (deflections, duels, restarts, saves) are
exactly where a sloppy reconstruction quietly invents or destroys possessions.

Works on the logged event stream, so it runs today on voice- and manually-entered
matches, and improves rather than changes when vision supplies more events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from analytics.query import distance_to_goal, in_box, minute_of, third_of

# Actions that hand the ball to the other side when they succeed. A tackle or an
# interception by Away ends Home's possession, so the *acting* team afterwards is
# the one that made them.
TURNOVER_ACTIONS = {"tackle", "interception", "clearance", "save", "block"}

# Actions that stop play outright: whatever follows starts a new possession for
# whoever restarts, regardless of who acted last.
STOPPAGE_ACTIONS = {"goal", "foul", "offside", "card", "yellow_card", "red_card",
                    "substitution", "corner", "throw_in", "goal_kick",
                    "free_kick", "penalty"}

# Restarts. A possession beginning with one of these is a set piece, which is a
# disproportionate share of youth goals and worth attributing correctly.
SET_PIECE_ACTIONS = {"corner", "free_kick", "throw_in", "goal_kick", "penalty"}

# A gap longer than this means play stopped even if nothing said so — a coach
# narrating live simply misses events, and pretending a possession spanned four
# minutes of silence would corrupt every duration metric built on it.
MAX_GAP_MINUTES = 1.5


@dataclass
class Possession:
    """One team's spell of control."""

    index: int
    team: Optional[str]
    events: List[dict] = field(default_factory=list)
    start_minute: Optional[float] = None
    end_minute: Optional[float] = None
    started_with: str = ""          # the action that began it
    start_type: str = "open_play"   # open_play | set_piece | turnover | restart

    @property
    def duration(self) -> Optional[float]:
        if self.start_minute is None or self.end_minute is None:
            return None
        return max(0.0, self.end_minute - self.start_minute)

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def passes(self) -> int:
        return sum(1 for e in self.events
                   if (e.get("action") or "").lower() == "pass")

    @property
    def ended_in_shot(self) -> bool:
        return any((e.get("action") or "").lower() in {"shot", "goal"}
                   or (e.get("result") or "").lower() == "scored"
                   for e in self.events)

    @property
    def ended_in_goal(self) -> bool:
        return any((e.get("action") or "").lower() == "goal"
                   or (e.get("result") or "").lower() == "scored"
                   for e in self.events)

    @property
    def reached_final_third(self) -> bool:
        return any(third_of(e.get("x")) == "final" for e in self.events)

    @property
    def reached_box(self) -> bool:
        return any(in_box(e.get("x"), e.get("y")) for e in self.events)

    @property
    def progression(self) -> Optional[float]:
        """Metres of ground gained toward goal across the possession."""
        located = [e for e in self.events if e.get("x") is not None]
        if len(located) < 2:
            return None
        first = distance_to_goal(located[0].get("x"), located[0].get("y"))
        last = distance_to_goal(located[-1].get("x"), located[-1].get("y"))
        if first is None or last is None:
            return None
        return first - last


def _team_after(event: dict) -> Optional[str]:
    """Which team holds the ball once this event has happened."""
    action = (event.get("action") or "").lower()
    team = event.get("team")
    if action in TURNOVER_ACTIONS:
        # The team that tackled/intercepted/saved now has it.
        return team
    return team


def _opposite(team: Optional[str]) -> Optional[str]:
    return {"Home": "Away", "Away": "Home"}.get(team)


def build(events, max_gap_minutes: float = MAX_GAP_MINUTES) -> List[Possession]:
    """Reconstruct possessions from an event log, in match order.

    Events with no team (unattributed narration) do not start a possession but
    are attached to the one in progress, since they describe it.
    """
    active = [e for e in (events or []) if (e.get("status") or "pending") != "denied"]
    possessions: List[Possession] = []
    current: Optional[Possession] = None
    last_minute: Optional[float] = None

    for e in active:
        action = (e.get("action") or "").lower()
        team = e.get("team")
        minute = minute_of(e)

        # A long silence means play stopped, whatever the events claim.
        gap = (minute is not None and last_minute is not None
               and (minute - last_minute) > max_gap_minutes)

        holder = _team_after(e)
        starts_new = (
            current is None
            or gap
            or (team is not None and holder != current.team)
            or (current.events
                and (current.events[-1].get("action") or "").lower()
                in STOPPAGE_ACTIONS)
        )

        if starts_new and team is not None:
            if current is not None:
                current.end_minute = last_minute
            start_type = ("set_piece" if action in SET_PIECE_ACTIONS
                          else "turnover" if action in TURNOVER_ACTIONS
                          else "open_play")
            current = Possession(index=len(possessions), team=holder,
                                 start_minute=minute, started_with=action,
                                 start_type=start_type)
            possessions.append(current)

        if current is not None:
            current.events.append(e)
            if minute is not None:
                current.end_minute = minute
        if minute is not None:
            last_minute = minute

    return possessions


# --------------------------------------------------------------------------- #
# Sequences
# --------------------------------------------------------------------------- #
@dataclass
class Sequence:
    """A coherent passage of play within a possession."""

    possession_index: int
    team: Optional[str]
    events: List[dict] = field(default_factory=list)
    start_minute: Optional[float] = None
    end_minute: Optional[float] = None

    @property
    def duration(self) -> Optional[float]:
        if self.start_minute is None or self.end_minute is None:
            return None
        return max(0.0, self.end_minute - self.start_minute)

    @property
    def passes(self) -> int:
        return sum(1 for e in self.events
                   if (e.get("action") or "").lower() == "pass")

    @property
    def directness(self) -> Optional[float]:
        """Metres gained per pass — high means direct, low means circulation."""
        gained = self.progression
        if gained is None or self.passes == 0:
            return None
        return gained / self.passes

    @property
    def progression(self) -> Optional[float]:
        located = [e for e in self.events if e.get("x") is not None]
        if len(located) < 2:
            return None
        a = distance_to_goal(located[0].get("x"), located[0].get("y"))
        b = distance_to_goal(located[-1].get("x"), located[-1].get("y"))
        return None if a is None or b is None else a - b

    def classify(self, fast_break_seconds: float = 15.0,
                 sustained_passes: int = 5) -> str:
        """Label the passage. Thresholds are arguments, not magic numbers."""
        if any((e.get("action") or "").lower() in SET_PIECE_ACTIONS
               for e in self.events[:1]):
            return "SET_PIECE"
        dur = self.duration
        if dur is not None and dur * 60 <= fast_break_seconds and self.ended_in_shot:
            return "FAST_BREAK"
        if self.passes >= sustained_passes:
            return "SUSTAINED_POSSESSION"
        if (self.directness or 0) > 15:
            return "DIRECT_ATTACK"
        return "BUILD_UP"

    @property
    def ended_in_shot(self) -> bool:
        return any((e.get("action") or "").lower() in {"shot", "goal"}
                   or (e.get("result") or "").lower() == "scored"
                   for e in self.events)


def sequences(possession: Possession,
              break_on: Optional[set] = None) -> List[Sequence]:
    """Split a possession into sequences at stoppages within it.

    A possession that survives a throw-in is still one possession, but the play
    either side of the restart is two passages, and directness measured across
    the break would be meaningless.
    """
    break_on = break_on or SET_PIECE_ACTIONS
    out: List[Sequence] = []
    current: Optional[Sequence] = None

    for e in possession.events:
        action = (e.get("action") or "").lower()
        minute = minute_of(e)
        if current is None or action in break_on:
            current = Sequence(possession_index=possession.index,
                               team=possession.team, start_minute=minute)
            out.append(current)
        current.events.append(e)
        if minute is not None:
            current.end_minute = minute
            if current.start_minute is None:
                current.start_minute = minute
    return out


def summarise(events) -> dict:
    """Possession-level totals for a match, for the report and the season view."""
    poss = build(events)
    by_team: dict = {}
    for p in poss:
        if p.team is None:
            continue
        row = by_team.setdefault(p.team, {
            "possessions": 0, "with_shot": 0, "with_goal": 0,
            "reached_final_third": 0, "reached_box": 0, "passes": 0,
            "total_duration": 0.0, "set_piece_starts": 0,
        })
        row["possessions"] += 1
        row["with_shot"] += int(p.ended_in_shot)
        row["with_goal"] += int(p.ended_in_goal)
        row["reached_final_third"] += int(p.reached_final_third)
        row["reached_box"] += int(p.reached_box)
        row["passes"] += p.passes
        row["total_duration"] += p.duration or 0.0
        row["set_piece_starts"] += int(p.start_type == "set_piece")

    for row in by_team.values():
        n = row["possessions"] or 1
        row["passes_per_possession"] = round(row["passes"] / n, 2)
        row["average_duration"] = round(row["total_duration"] / n, 2)
        row["shot_rate"] = round(100 * row["with_shot"] / n, 1)
    return by_team
