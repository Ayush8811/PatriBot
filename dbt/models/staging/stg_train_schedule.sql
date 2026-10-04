-- Silver: one row per train × timetable route stop (RailKit train info lists stopping stations only).
-- Clock times are "HH:MM" local (IST); day offsets are 0 on the day the train leaves its origin. day_offset is the
-- arrival's day (the departure's at the origin), dep_day_offset the departure's (later when a halt crosses midnight).
select
    train_no || ':' || lpad(cast(seq as varchar), 3, '0') as train_stop_id,
    source,
    train_no,
    seq,
    upper(station_code) as station_code,
    nullif(trim(station_name), '') as station_name,
    arr as arr_time,
    dep as dep_time,
    cast(split_part(arr, ':', 1) as integer) * 60 + cast(split_part(arr, ':', 2) as integer) as arr_clock_min,
    cast(split_part(dep, ':', 1) as integer) * 60 + cast(split_part(dep, ':', 2) as integer) as dep_clock_min,
    day_offset,
    coalesce(dep_day_offset, day_offset) as dep_day_offset,
    distance_km,
    halt_min,
    coalesce(halts, true) as halts,
    platform,
    lat,
    lon
from {{ source('silver_input', 'train_schedule') }}
