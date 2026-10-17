-- Raising preflop is always a voluntary action, so PFR without VPIP means a parser bug.
select * from {{ ref('fct_player_hands') }} where pfr and not vpip
