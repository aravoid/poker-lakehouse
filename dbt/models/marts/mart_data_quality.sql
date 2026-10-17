-- Data-quality scoreboard: how complete is the data, and why were hands rejected?
select 'hands_parsed' as metric, count(*) as value from {{ ref('stg_hands') }}
union all
select 'outcome_' || outcome_source, count(*) from {{ ref('stg_hands') }} group by outcome_source
union all
select 'quarantined_total', count(*) from {{ ref('stg_quarantine') }}
union all
select 'quarantined_' || error_type, count(*) from {{ ref('stg_quarantine') }} group by error_type
