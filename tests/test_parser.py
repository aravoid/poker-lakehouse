import pytest

from poker_pipeline.parser import ParseError, parse_hand, position_names

# A real-shaped hand: everyone folds to p5, who raised to 8 (only 2 is ever called: 6 is returned)
FOLD_WIN = """[2]
variant = 'NT'
antes = [0, 0, 0, 0, 0, 0]
blinds_or_straddles = [1, 2, 0, 0, 0, 0]
min_bet = 2
starting_stacks = [38, 199.75, 294.70, 144.45, 318.70, 200]
actions = ['d dh p1 ????', 'd dh p2 ????', 'd dh p3 ????', 'd dh p4 ????', 'd dh p5 ????', 'd dh p6 ????', 'p3 f', 'p4 f', 'p5 cbr 8', 'p6 f', 'p1 f', 'p2 f']
venue = 'PokerStars'
day = 1
month = 7
year = 2009
hand = 59937793454
seats = [6, 1, 2, 3, 4, 5]
table = 'ztv6V3FN2bQ9nmJPPdx6nQ'
players = ['a', 'b', 'c', 'd', 'e', 'f']
winnings = [0, 0, 0, 0, 5, 0]
"""

# Showdown: p1 and p3 see the river; no winnings listed, so the outcome is unknown
SHOWDOWN = """[1]
variant = 'NT'
antes = [0, 0, 0]
blinds_or_straddles = [1, 2, 0]
starting_stacks = [100, 100, 100]
actions = ['d dh p1 ????', 'p3 cbr 6', 'p1 cc', 'p2 f', 'd db AhKd7c', 'p1 cc', 'p3 cc', 'd db 2s', 'p1 cc', 'p3 cc', 'd db 9h', 'p1 cc', 'p3 cc', 'p1 sm AsAd', 'p3 sm KsKd']
venue = 'PokerStars'
day = 2
month = 7
year = 2009
hand = 11
seats = [1, 2, 3]
players = ['a', 'b', 'c']
"""


def swap(text, old, new):
    assert old in text
    return text.replace(old, new)


def test_recorded_winnings_and_uncalled_bet_refund():
    h = parse_hand(FOLD_WIN)
    by = {p.name: p for p in h.players}
    assert h.outcome_source == "recorded" and h.hand_id == "59937793454"
    assert by["e"].invested == 2.0      # raised to 8, but only 2 was matched: 6 comes back
    assert by["e"].collected == 5.0 and h.rake == 0.0
    assert by["a"].invested == 1.0 and by["b"].invested == 2.0
    assert h.big_blind == 2.0 and h.played_date == "2009-07-01"


def test_positions_count_from_the_small_blind():
    assert position_names(6) == ["SB", "BB", "UTG", "HJ", "CO", "BTN"]
    assert position_names(2) == ["SB", "BB"]
    by = {p.name: p.position for p in parse_hand(FOLD_WIN).players}
    assert by["e"] == "CO" and by["f"] == "BTN" and by["c"] == "UTG"


def test_vpip_and_pfr_flags():
    text = swap(FOLD_WIN, "'p3 f', 'p4 f', 'p5 cbr 8'", "'p3 cc', 'p4 f', 'p5 cbr 8'")
    text = swap(text, "'p1 f', 'p2 f']", "'p1 f', 'p2 f', 'p3 f']")   # the limper folds to the raise
    text = swap(text, "[0, 0, 0, 0, 5, 0]", "[0, 0, 0, 0, 7, 0]")     # pot is now 1 + 2 + 2 + 2
    by = {p.name: p for p in parse_hand(text).players}
    assert by["e"].vpip and by["e"].pfr           # raised
    assert by["c"].vpip and not by["c"].pfr       # limped
    assert not by["d"].vpip                       # folded


def test_big_blind_checking_is_not_vpip():
    text = swap(FOLD_WIN, "'p5 cbr 8', 'p6 f', 'p1 f', 'p2 f'", "'p5 f', 'p6 f', 'p1 f', 'p2 cc'")
    text = swap(text, "winnings = [0, 0, 0, 0, 5, 0]", "winnings = [0, 2, 0, 0, 0, 0]")
    by = {p.name: p for p in parse_hand(text).players}
    assert not by["b"].vpip


def test_fold_win_without_winnings_is_inferred():
    text = swap(FOLD_WIN, "winnings = [0, 0, 0, 0, 5, 0]\n", "")
    h = parse_hand(text)
    by = {p.name: p for p in h.players}
    assert h.outcome_source == "inferred_fold" and by["e"].collected == 5.0
    assert by["a"].collected == 0.0


def test_showdown_without_winnings_is_unknown_not_guessed():
    h = parse_hand(SHOWDOWN)
    assert h.outcome_source == "unknown"
    assert all(p.collected is None for p in h.players)


def test_recorded_winnings_below_pot_become_rake():
    h = parse_hand(swap(FOLD_WIN, "winnings = [0, 0, 0, 0, 5, 0]", "winnings = [0, 0, 0, 0, 4.75, 0]"))
    assert h.rake == 0.25


def test_negative_blind_at_big_blind_size_is_a_live_post():
    text = """[1]
variant = 'NT'
blinds_or_straddles = [1, 2, -2]
starting_stacks = [100, 100, 100]
actions = ['p3 cc', 'p1 cc', 'p2 cc', 'd db AhKd7c', 'p1 cbr 4', 'p2 f', 'p3 f']
venue = 'PokerStars'
day = 1
month = 7
year = 2009
hand = 5
seats = [1, 2, 3]
players = ['a', 'b', 'c']
winnings = [6, 0, 0]
"""
    h = parse_hand(text)
    by = {p.name: p for p in h.players}
    assert by["c"].invested == 2.0 and not by["c"].vpip   # the post was live: p3 just checked
    assert h.outcome_source == "recorded" and h.rake == 0.0


def test_negative_blind_below_big_blind_is_dead_money():
    text = swap(FOLD_WIN, "blinds_or_straddles = [1, 2, 0, 0, 0, 0]", "blinds_or_straddles = [1, 2, 0, 0, -1, 0]")
    text = swap(text, "winnings = [0, 0, 0, 0, 5, 0]", "winnings = [0, 0, 0, 0, 6, 0]")
    h = parse_hand(text)
    assert h.rake == 0.0 and {p.name: p for p in h.players}["e"].invested == 3.0


def test_flat_phh_without_section_header_also_parses():
    assert parse_hand(FOLD_WIN.replace("[2]\n", "")).hand_id == "59937793454"


@pytest.mark.parametrize("bad, reason", [
    (lambda t: t[: len(t) // 2], "invalid TOML"),
    (lambda t: swap(t, "venue =", "??? connection lost ???\nvenue ="), "invalid TOML"),
    (lambda t: swap(t, "variant = 'NT'", "variant = 'FT'"), "unsupported variant"),
    (lambda t: swap(t, "hand = 59937793454\n", ""), "missing field"),
    (lambda t: swap(t, "'p3 f'", "'p3 shrug'"), "unknown action"),
    (lambda t: swap(t, "'p3 f'", "'p9 f'"), "unknown actor"),
    (lambda t: swap(t, "[0, 0, 0, 0, 5, 0]", "[0, 0, 0, 0, 50, 0]"), "winnings exceed pot"),
    (lambda t: swap(t, "[0, 0, 0, 0, 5, 0]", "[0, 0, 0, 0, 1, 0]"), "implausible rake"),
    (lambda t: swap(t, "players = ['a', 'b', 'c', 'd', 'e', 'f']", "players = ['a', 'a', 'c', 'd', 'e', 'f']"), "duplicate player"),
])
def test_bad_hands_are_rejected_with_a_reason(bad, reason):
    with pytest.raises(ParseError, match=reason):
        parse_hand(bad(FOLD_WIN))
