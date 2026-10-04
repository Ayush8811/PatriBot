-- Gold: every train seen by the collector or listed in the timetable. Timetable attributes (name, type, running
-- days at origin, classes, corridors) where a schedule is cached; run counts from the running data.
-- (Not SCD-2 yet: the latest timetable wins.)
with runs as (
    select
        train_no,
        arg_max(train_name, start_date) filter (where train_name is not null) as train_name,
        arg_max(origin_code, start_date) filter (where origin_code is not null) as origin_code,
        arg_max(destination_code, start_date) filter (where destination_code is not null) as destination_code,
        max(route_km) as route_km,
        count(*) as n_runs_attempted,
        count(*) filter (where run_state = 'complete') as n_runs_complete,
        min(start_date) as first_start_date,
        max(start_date) as last_start_date
    from {{ ref('fct_run_summary') }}
    group by train_no
),

tt as (
    select * from {{ ref('stg_train_info') }}
),

route as (
    select train_no, max(distance_km) as route_km
    from {{ ref('stg_train_schedule') }}
    group by train_no
),

corridors as (
    select train_no, string_agg(corridor_id, ',' order by corridor_id) as corridor_ids
    from {{ ref('dim_train_corridor') }}
    group by train_no
),

keys as (
    select train_no from runs
    union
    select train_no from tt
)

select
    k.train_no,
    -- providers truncate names (RailKit timetable: 15 characters); keep the longer one
    case
        when length(r.train_name) > length(coalesce(tt.train_name, '')) then r.train_name else tt.train_name
    end as train_name,
    tt.train_type_display as train_type,
    tt.train_type_raw,
    coalesce(tt.origin_code, r.origin_code) as origin_code,
    coalesce(tt.destination_code, r.destination_code) as destination_code,
    tt.dep_time,
    tt.arr_time,
    tt.travel_minutes,
    tt.running_days,  -- "MON,TUE,..." at the origin; NULL without a timetable
    tt.classes,  -- "1A,2A,3A"; empty when unknown
    coalesce(rt.route_km, r.route_km) as route_km,
    c.corridor_ids,
    tt.train_no is not null as has_timetable,
    coalesce(tt.is_reserved, true) as is_reserved,  -- the collector only watches reserved trains
    tt.exclusion_reason,
    coalesce(r.n_runs_attempted, 0) as n_runs_attempted,
    coalesce(r.n_runs_complete, 0) as n_runs_complete,
    r.first_start_date,
    r.last_start_date,
    tt.fetched_at as timetable_fetched_at
from keys as k
left join runs as r using (train_no)
left join tt using (train_no)
left join route as rt using (train_no)
left join corridors as c using (train_no)
