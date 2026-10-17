select position as item, vpip_pct, pfr_pct from {{ ref('mart_position_stats') }}
where vpip_pct not between 0 and 100 or pfr_pct not between 0 and 100 or pfr_pct > vpip_pct
union all
select player, vpip_pct, pfr_pct from {{ ref('mart_player_profiles') }}
where vpip_pct not between 0 and 100 or pfr_pct not between 0 and 100 or pfr_pct > vpip_pct
