"""Parse one hand in the PHH (Poker Hand History) format into structured data.

PHH is an open, TOML-based format (https://phh.readthedocs.io). One hand looks like:

    [1]
    variant = 'NT'                              # no-limit hold'em
    blinds_or_straddles = [1, 2, 0, 0, 0]       # p1 = small blind, p2 = big blind ...
    starting_stacks = [247.15, 237.05, 47.90, 208.75, 269.45]
    actions = ['d dh p1 ????', 'p3 cc', 'p4 f', 'p2 cbr 4', 'd db 6hTdKd', ...]
    hand = 59937793530
    winnings = [0, 0, 0, 5, 0]
    ...

The parser is pure Python (no Spark) so it is easy to unit test. The pipeline wraps
`parse_hand` in a UDF. Anything it cannot parse, or that fails a consistency check, raises
ParseError, and the pipeline sends that hand to a quarantine table instead of crashing.

Action codes used here:  f = fold, cc = check/call, cbr N = bet/raise *to* N on this street,
d dh / d db = deal hole cards / board (street changes), sm = show/muck (ignored).
Players are numbered p1..pN starting at the small blind; the last player is the button.
"""
import re
from dataclasses import dataclass, field

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

STREETS = ["preflop", "flop", "turn", "river"]
PLAYER_TOKEN = re.compile(r"^p(\d+)$")
EPS = 0.011  # chips are dollars with cents: allow rounding noise


class ParseError(ValueError):
    pass


def position_names(n):
    """Position of p1..pN. p1 = SB, p2 = BB, last = BTN, then CO, HJ counting back."""
    names = []
    for i in range(1, n + 1):
        d = n - i  # distance from the button
        if i == 1:
            names.append("SB")
        elif i == 2:
            names.append("BB")
        elif d == 0:
            names.append("BTN")
        elif d == 1:
            names.append("CO")
        elif d == 2:
            names.append("HJ")
        elif i == 3:
            names.append("UTG")
        else:
            names.append("MP")
    return names


@dataclass
class Player:
    seat: int
    name: str
    stack: float
    position: str
    invested: float = 0.0   # chips actually committed (uncalled bets are returned)
    collected: float = None  # chips won from the pot; None when the outcome is unknown
    vpip: bool = False      # voluntarily put money in preflop (call or raise)
    pfr: bool = False       # raised preflop


@dataclass
class Hand:
    hand_id: str
    venue: str
    played_date: str
    table_name: str
    small_blind: float
    big_blind: float
    n_players: int
    rake: float
    outcome_source: str  # recorded | inferred_fold | unknown (see parse_hand)
    players: list = field(default_factory=list)
    actions: list = field(default_factory=list)  # (seq, street, player, action, amount)


def _num(x, what):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ParseError(f"{what} is not a number")
    return float(x)


def parse_hand(text: str) -> Hand:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ParseError("invalid TOML (corrupt or truncated hand)") from None
    # A .phhs file wraps each hand in a [N] table; a plain .phh file is flat.
    h = doc if "variant" in doc else (next(iter(doc.values())) if len(doc) == 1 else None)
    if not isinstance(h, dict):
        raise ParseError("no hand found")

    if h.get("variant") != "NT":
        raise ParseError(f"unsupported variant: {h.get('variant')}")
    for key in ("actions", "starting_stacks", "blinds_or_straddles", "players",
                "seats", "hand", "venue", "year", "month", "day"):
        if key not in h:
            raise ParseError(f"missing field: {key}")

    stacks = [_num(s, "stack") for s in h["starting_stacks"]]
    n = len(stacks)
    blinds = [_num(b, "blind") for b in h["blinds_or_straddles"]]
    antes = [_num(a, "ante") for a in h.get("antes", [0] * n)]
    names, seats = list(h["players"]), list(h["seats"])
    if n < 2:
        raise ParseError("fewer than 2 players")
    if not (len(blinds) == len(antes) == len(names) == len(seats) == n):
        raise ParseError("player-list length mismatch")
    if len(set(names)) != n:
        raise ParseError("duplicate player in hand")
    if blinds[0] <= 0 or blinds[1] <= 0:
        raise ParseError("missing blinds")

    # Chips committed so far: antes and blinds (capped at the stack). Real data encodes a
    # player who posts out of turn (e.g. to re-enter) as a NEGATIVE blind. Validated against
    # recorded winnings on real hands: a post of at least the big blind is a live bet, a
    # smaller one is dead money (in the pot, but not part of the amount others must call).
    big = blinds[1]
    live = [i for i in range(n) if blinds[i] > 0 or abs(blinds[i]) >= big]
    invested = [min(antes[i] + abs(blinds[i]), stacks[i]) for i in range(n)]
    dead = [min(abs(blinds[i]), stacks[i]) if i not in live else 0.0 for i in range(n)]
    street_c = [min(abs(blinds[i]), stacks[i]) if i in live else 0.0 for i in range(n)]
    remaining = [stacks[i] - invested[i] for i in range(n)]
    vpip, pfr, folded = [False] * n, [False] * n, [False] * n
    current_bet, street_idx, seq, actions = max(street_c), 0, 0, []

    for token in h["actions"]:
        parts = str(token).split()
        if len(parts) < 2:
            raise ParseError(f"bad action: {token!r}")
        if parts[0] == "d":
            if parts[1] == "db":
                street_idx += 1
                if street_idx >= len(STREETS):
                    raise ParseError("too many board deals")
                street_c, current_bet = [0.0] * n, 0.0
            elif parts[1] != "dh":
                raise ParseError(f"bad deal: {token!r}")
            continue
        m = PLAYER_TOKEN.match(parts[0])
        if not m or not 1 <= int(m.group(1)) <= n:
            raise ParseError(f"unknown actor: {token!r}")
        i, op, street = int(m.group(1)) - 1, parts[1], STREETS[street_idx]
        if op == "sm":  # show/muck: no chips move
            continue
        seq += 1
        if op == "f":
            folded[i] = True
            actions.append((seq, street, names[i], "folds", 0.0))
        elif op == "cc":
            owed = current_bet - street_c[i]
            amt = max(0.0, min(owed, remaining[i]))
            if owed > EPS:
                if street_idx == 0:
                    vpip[i] = True
                act = "calls"
            else:
                act = "checks"
            street_c[i] += amt
            invested[i] += amt
            remaining[i] -= amt
            actions.append((seq, street, names[i], act, amt))
        elif op == "cbr":
            if len(parts) != 3:
                raise ParseError(f"bad raise: {token!r}")
            try:
                target = float(parts[2])
            except ValueError:
                raise ParseError(f"bad raise amount: {token!r}") from None
            amt = min(target - street_c[i], remaining[i])
            if amt <= 0:
                raise ParseError(f"non-positive raise: {token!r}")
            act = "bets" if current_bet == 0 else "raises"
            street_c[i] += amt
            invested[i] += amt
            remaining[i] -= amt
            current_bet = max(current_bet, street_c[i])
            if street_idx == 0:
                vpip[i] = pfr[i] = True
            actions.append((seq, street, names[i], act, amt))
        else:
            raise ParseError(f"unknown action: {token!r}")

    # Uncalled bet: whatever the top contributor put in above the second-highest is returned.
    in_play = [invested[k] - dead[k] for k in range(n)]  # dead money cannot be 'called'
    order = sorted(range(n), key=lambda k: in_play[k], reverse=True)
    uncalled = in_play[order[0]] - in_play[order[1]]
    if uncalled > EPS:
        invested[order[0]] -= uncalled

    # Who won what? Real data is incomplete, so be explicit about how we know:
    #   recorded       the file lists winnings (use them, derive rake = pot - winnings)
    #   inferred_fold  no winnings listed, but everyone except one player folded: that player won
    #   unknown        showdown with no winnings listed: outcome is NOT guessed (left empty)
    pot = sum(invested)
    raw = h.get("winnings")
    winnings = [_num(w, "winnings") for w in raw] if raw is not None else None
    if winnings is not None and len(winnings) != n:
        raise ParseError("winnings length mismatch")
    active = [k for k in range(n) if not folded[k]]
    if winnings is not None and sum(winnings) > EPS:
        rake = round(pot - sum(winnings), 2)
        if rake < -EPS:
            raise ParseError(f"winnings exceed pot: pot={pot:.2f} won={sum(winnings):.2f}")
        if rake > 0.25 * pot + EPS:
            raise ParseError(f"implausible rake: pot={pot:.2f} won={sum(winnings):.2f}")
        collected, source = winnings, "recorded"
    elif len(active) == 1:
        collected = [pot if k == active[0] else 0.0 for k in range(n)]
        rake, source = 0.0, "inferred_fold"
    else:
        collected, rake, source = [None] * n, 0.0, "unknown"

    pos = position_names(n)
    players = [Player(int(seats[i]), names[i], stacks[i], pos[i], invested[i], collected[i],
                      vpip[i], pfr[i]) for i in range(n)]
    played = f"{int(h['year']):04d}-{int(h['month']):02d}-{int(h['day']):02d}"
    return Hand(str(h["hand"]), str(h["venue"]), played, str(h.get("table", "")),
                blinds[0], blinds[1], n, max(rake, 0.0), source, players, actions)
