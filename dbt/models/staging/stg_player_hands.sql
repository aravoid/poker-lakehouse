-- One row per player per hand.
-- `net` / `net_bb` are NULL when the outcome of the hand is unknown (never guessed).
select
    hand_id,
    venue,
    player,
    seat,
    position,
    stack,
    big_blind,
    invested,
    collected,
    net,
    net_bb,
    vpip,
    pfr,
    outcome_source
from {{ source('silver', 'player_hands') }}
