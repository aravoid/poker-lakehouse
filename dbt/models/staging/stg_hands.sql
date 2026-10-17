-- One row per parsed hand. Staging only renames and casts; no business logic.
select
    hand_id,
    venue,
    played_date,
    table_name,
    cast(small_blind as double) as small_blind,
    cast(big_blind as double)   as big_blind,
    n_players,
    rake,
    outcome_source,
    source_file
from {{ source('silver', 'hands') }}
