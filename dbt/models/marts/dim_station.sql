-- Gold: every station seen in running data or named in the corridor config, with its cluster and corridor roles.
with observed as (
    select
        station_code,
        mode(station_name) as station_name,  -- the most frequently reported name; NULL names are ignored
        count(*) as n_stop_events,
        min(start_date) as first_seen_date,
        max(start_date) as last_seen_date
    from {{ ref('stg_train_run_stop') }}
    group by station_code
),

waypoints as (
    select
        station_code,
        string_agg(distinct corridor_id, ',' order by corridor_id) as corridor_ids
    from {{ ref('seed_corridor_waypoint') }}
    group by station_code
),

hubs as (
    select distinct station_code from {{ ref('seed_corridor_split_hub') }}
),

all_codes as (
    select station_code from observed
    union
    select station_code from {{ ref('seed_station_cluster') }}
    union
    select station_code from waypoints
    union
    select station_code from hubs
)

select
    a.station_code,
    o.station_name,
    c.cluster_id,
    w.station_code is not null as is_corridor_waypoint,
    w.corridor_ids,
    h.station_code is not null as is_split_hub,
    coalesce(o.n_stop_events, 0) as n_stop_events,
    o.first_seen_date,
    o.last_seen_date
from all_codes as a
left join observed as o using (station_code)
left join {{ ref('seed_station_cluster') }} as c using (station_code)
left join waypoints as w using (station_code)
left join hubs as h using (station_code)
