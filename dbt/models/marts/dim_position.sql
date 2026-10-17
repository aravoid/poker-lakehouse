select position, seat_order, position_group
from {{ ref('positions') }}
