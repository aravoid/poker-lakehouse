-- One row per (anonymized) player.
select
    ph.player,
    count(*)           as hands_played,
    min(h.played_date) as first_seen,
    max(h.played_date) as last_seen
from {{ ref('stg_player_hands') }} ph
join {{ ref('stg_hands') }} h
  on ph.hand_id = h.hand_id and ph.venue = h.venue
group by ph.player
