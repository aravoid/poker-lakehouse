-- Fact table. Grain: one row per player per hand.
select
    ph.hand_id,
    ph.venue,
    ph.player,
    h.played_date,
    h.table_name,
    h.n_players,
    ph.position,
    ph.big_blind,
    ph.invested,
    ph.collected,
    ph.net,
    ph.net_bb,
    ph.vpip,
    ph.pfr,
    ph.outcome_source,
    (ph.net_bb is not null) as has_result
from {{ ref('stg_player_hands') }} ph
join {{ ref('stg_hands') }} h
  on ph.hand_id = h.hand_id and ph.venue = h.venue
