-- Hands the parser rejected, with the reason grouped into a short error type.
select
    hand_id,
    source_file,
    error,
    split_part(error, ':', 1) as error_type
from {{ source('silver', 'quarantine') }}
