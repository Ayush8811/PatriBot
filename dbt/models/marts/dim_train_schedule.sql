-- Gold: scheduled stop times per train as minutes from the ORIGIN departure, the form the planner works in.
-- A stop's departure date for a run = run_date + floor((origin_dep_clock_min + dep_min) / 1440) days.
with s as (
    select * from {{ ref('stg_train_schedule') }}
),

origin as (
    select train_no, dep_clock_min as origin_dep_clock_min
    from s
    where seq = 1
),

ends as (
    select train_no, max(seq) as last_seq, max(distance_km) as route_km
    from s
    group by train_no
),

timed as (
    select
        s.*,
        o.origin_dep_clock_min,
        e.last_seq,
        e.route_km,
        case when s.arr_clock_min is not null
            then s.day_offset * 1440 + s.arr_clock_min - o.origin_dep_clock_min
        end as arr_min
    from s
    inner join origin as o using (train_no)
    inner join ends as e using (train_no)
),

final as (
    select
        *,
        case when dep_clock_min is not null
            then dep_day_offset * 1440 + dep_clock_min - origin_dep_clock_min
        end as dep_min
    from timed
)

select
    f.train_stop_id,
    f.train_no,
    f.seq,
    f.station_code,
    f.station_name,
    c.cluster_id,
    f.arr_time,
    f.dep_time,
    f.day_offset,
    f.dep_day_offset,
    f.arr_min,
    f.dep_min,
    f.origin_dep_clock_min,
    f.dep_min - lag(f.dep_min) over w as dep_gap_min,
    f.arr_min - lag(f.dep_min) over w as sched_segment_min,
    f.distance_km,
    f.route_km,
    case when f.route_km > 0 then least(1.0, f.distance_km / f.route_km) end as route_fraction,
    f.halt_min,
    f.halts,
    f.seq = 1 as is_origin,
    f.seq = f.last_seq as is_destination,
    f.platform,
    f.lat,
    f.lon,
    f.source
from final as f
left join {{ ref('seed_station_cluster') }} as c using (station_code)
window w as (partition by f.train_no order by f.seq)
