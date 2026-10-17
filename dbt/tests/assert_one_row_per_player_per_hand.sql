-- The grain of fct_player_hands: no (venue, hand, player) may appear twice.
select venue, hand_id, player, count(*) as n
from {{ ref('fct_player_hands') }}
group by venue, hand_id, player
having count(*) > 1
