"""Generate synthetic hand-history files in the PHH format.

Why: lets you test the pipeline at any scale, with known ground truth. It injects the same
kinds of mess real data has (missing winnings, showdowns with no recorded result) plus
deliberate corruption (truncated hands, garbage lines, impossible pots) and duplicates,
and returns exact counts so tests can check the pipeline found every one of them.

NOTE: outcomes are random, so statistics from this data demonstrate the pipeline, not poker
strategy. Use real hands (scripts/download_sample.py) for real analysis.

    python -m poker_pipeline.simulator --out data/sim --hands 5000 --files 5
"""
import argparse
import random
from pathlib import Path

POOL = [f"sim_player{n:02d}" for n in range(1, 41)]
SB, BB = 1, 2


def _n(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _round(rng, acts, order, active, street_in, current_bet, invested, fold_p):
    """One betting round: a first pass, then everyone who owes calls or folds."""
    for p in order:
        if len(active) == 1:
            return current_bet
        if p not in active:
            continue
        owe = current_bet - street_in[p]
        r = rng.random()
        if owe <= 0:
            if r < 0.7:
                acts.append(f"p{p + 1} cc")
                continue
            amt = float(rng.choice([2, 4, 6]))
        elif r < fold_p:
            acts.append(f"p{p + 1} f")
            active.discard(p)
            continue
        elif r < fold_p + 0.15:
            amt = (current_bet + rng.choice([4, 6, 8])) - street_in[p]
        else:
            acts.append(f"p{p + 1} cc")
            street_in[p] += owe
            invested[p] += owe
            continue
        street_in[p] += amt
        invested[p] += amt
        current_bet = max(current_bet, street_in[p])
        acts.append(f"p{p + 1} cbr {_n(street_in[p])}")
    while len(active) > 1:
        owing = [p for p in order if p in active and street_in[p] < current_bet]
        if not owing:
            break
        for p in owing:
            if len(active) == 1:
                break
            if rng.random() < 0.4:
                acts.append(f"p{p + 1} f")
                active.discard(p)
            else:
                owe = current_bet - street_in[p]
                acts.append(f"p{p + 1} cc")
                street_in[p] += owe
                invested[p] += owe
    return current_bet


def generate_hand(rng, hand_id, day):
    """Returns (phh_text, outcome_kind); outcome_kind is what the pipeline should report."""
    n = rng.choice([4, 5, 6, 6, 6, 8, 9])
    names = rng.sample(POOL, n)
    stacks = [round(rng.uniform(100, 300), 2) for _ in range(n)]
    blinds = [SB, BB] + [0] * (n - 2)
    invested = [float(b) for b in blinds]
    street_in = list(invested)
    active = set(range(n))
    acts = [f"d dh p{i + 1} ????" for i in range(n)]
    current = _round(rng, acts, list(range(2, n)) + [0, 1], active, street_in, BB,
                     invested, fold_p=0.6)
    for k in range(3):
        if len(active) < 2:
            break
        acts.append("d db " + ["AhKd7c", "2s", "9h"][k])
        street_in = [0.0] * n
        _round(rng, acts, list(range(n)), active, street_in, 0.0, invested, fold_p=0.35)

    order = sorted(range(n), key=lambda k: invested[k], reverse=True)
    uncalled = invested[order[0]] - invested[order[1]]
    invested[order[0]] -= uncalled
    pot = sum(invested)
    winner = rng.choice(sorted(active))
    won = [0.0] * n
    won[winner] = pot
    record = rng.random() < 0.5
    kind = "recorded" if record else ("inferred_fold" if len(active) == 1 else "unknown")

    lines = [
        "variant = 'NT'", "ante_trimming_status = false",
        f"antes = [{', '.join(['0'] * n)}]",
        f"blinds_or_straddles = [{', '.join(str(b) for b in blinds)}]", f"min_bet = {BB}",
        f"starting_stacks = [{', '.join(_n(s) for s in stacks)}]",
        "actions = [" + ", ".join(f"'{a}'" for a in acts) + "]",
        "venue = 'Simulated'", "time = 00:00:00", f"day = {day}", "month = 1", "year = 2026",
        f"hand = {hand_id}", f"seats = [{', '.join(str(i + 1) for i in range(n))}]",
        f"seat_count = {n}", f"table = 'sim{rng.randint(1, 9)}'",
        "players = [" + ", ".join(f"'{p}'" for p in names) + "]",
    ]
    if record:
        lines.append(f"winnings = [{', '.join(_n(w) for w in won)}]")
    lines += ["currency_symbol = '$'", "time_zone_abbreviation = 'ET'"]
    return lines, kind


def _corrupt(rng, lines):
    mode = rng.choice(["truncate", "garbage", "pot_mismatch"])
    lines = list(lines)
    if mode == "pot_mismatch" and any(ln.startswith("winnings") for ln in lines):
        i = next(k for k, ln in enumerate(lines) if ln.startswith("winnings"))
        lines[i] = "winnings = [999, 0, 0, 0]"
        return lines
    if mode == "truncate":
        cut = next(k for k, ln in enumerate(lines) if ln.startswith("actions"))
        return lines[: rng.randint(2, cut)]
    lines.insert(rng.randint(1, len(lines) - 1), "??? connection lost ???")
    return lines


def write_files(out_dir, n_hands, n_files, seed=42, corrupt_rate=0.03, dup_rate=0.02):
    rng = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    buckets = [[] for _ in range(n_files)]
    stats = {"hands": n_hands, "corrupted": 0, "duplicates": 0, "files": n_files,
             "recorded": 0, "inferred_fold": 0, "unknown": 0}
    for i in range(n_hands):
        lines, kind = generate_hand(rng, 7_000_000_000 + i, 1 + i % 28)
        if rng.random() < corrupt_rate:
            buckets[i % n_files].append(("\n".join(_corrupt(rng, lines))))
            stats["corrupted"] += 1
            continue
        stats[kind] += 1
        buckets[i % n_files].append("\n".join(lines))
        if rng.random() < dup_rate:  # same hand shows up again in another file
            buckets[(i + 1) % n_files].append("\n".join(lines))
            stats["duplicates"] += 1
    for k, hands in enumerate(buckets):
        text = "\n\n".join(f"[{j + 1}]\n{h}" for j, h in enumerate(hands))
        (out / f"sim_{k:03d}.phhs").write_text(text + "\n")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sim")
    ap.add_argument("--hands", type=int, default=5000)
    ap.add_argument("--files", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    print(write_files(a.out, a.hands, a.files, a.seed))
