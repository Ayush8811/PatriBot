-- Gold: station → city cluster mapping (config/corridors.yaml `clusters`). One row per member station.
with clusters as (
    select * from {{ ref('seed_station_cluster') }}
),

observed as (
    select distinct station_code from {{ ref('stg_train_run_stop') }}
)

select
    c.station_code,
    c.cluster_id,
    -- display name: "BENGALURU" → "Bengaluru"
    upper(substr(c.cluster_id, 1, 1)) || lower(substr(c.cluster_id, 2)) as cluster_name,
    c.cluster_rank,
    o.station_code is not null as is_observed
from clusters as c
left join observed as o using (station_code)
