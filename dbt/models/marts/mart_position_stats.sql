-- Behaviour (VPIP/PFR) uses every hand. Win rate uses only hands with a known outcome,
-- and result_coverage_pct says how many that is.
select
    f.position,
    d.position_group,
    d.seat_order,
    count(*)                                              as hands,
    round(avg(case when f.vpip then 1.0 else 0.0 end) * 100, 1) as vpip_pct,
    round(avg(case when f.pfr  then 1.0 else 0.0 end) * 100, 1) as pfr_pct,
    count(f.net_bb)                                       as hands_with_result,
    round(count(f.net_bb) * 100.0 / count(*), 1)          as result_coverage_pct,
    round(avg(f.net_bb) * 100, 2)                         as bb_per_100_known
from {{ ref('fct_player_hands') }} f
join {{ ref('dim_position') }} d on f.position = d.position
group by f.position, d.position_group, d.seat_order
