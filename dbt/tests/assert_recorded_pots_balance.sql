-- For hands with recorded winnings, chips paid out can never exceed chips put in
-- (the difference is rake). Returns the offending hands.
select venue, hand_id, sum(invested) as put_in, sum(collected) as paid_out
from {{ ref('fct_player_hands') }}
where outcome_source = 'recorded'
group by venue, hand_id
having sum(collected) > sum(invested) + 0.011
