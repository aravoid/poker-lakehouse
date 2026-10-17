-- Unknown outcomes must stay NULL (never guessed).
select * from {{ ref('fct_player_hands') }}
where outcome_source = 'unknown' and net is not null
