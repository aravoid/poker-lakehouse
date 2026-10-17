-- One row per player with enough hands to say something about their style.
-- Doubles as a feature table for a later ML step (e.g. predicting player type).
with agg as (
    select
        player,
        count(*)                                              as hands,
        avg(case when vpip then 1.0 else 0.0 end) * 100       as vpip_pct,
        avg(case when pfr  then 1.0 else 0.0 end) * 100       as pfr_pct,
        count(net_bb)                                         as hands_with_result,
        avg(net_bb) * 100                                     as bb_per_100_known
    from {{ ref('fct_player_hands') }}
    group by player
)
select
    player,
    hands,
    round(vpip_pct, 1) as vpip_pct,
    round(pfr_pct, 1)  as pfr_pct,
    case when vpip_pct < 20 then 'tight'
         when vpip_pct < 30 then 'standard'
         else 'loose' end as looseness,
    case when vpip_pct = 0 then null
         when pfr_pct / vpip_pct >= 0.7 then 'aggressive'
         when pfr_pct / vpip_pct >= 0.4 then 'balanced'
         else 'passive' end as aggression,
    hands_with_result,
    round(bb_per_100_known, 2) as bb_per_100_known
from agg
where hands >= {{ var('min_hands_for_profile') }}
