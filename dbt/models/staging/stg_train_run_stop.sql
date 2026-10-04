-- Silver: one row per run × stop. Scheduled vs actual times in IST, day offsets resolved against the start date.
with stops as (
    select
        source || ':' || train_no || ':' || strftime(start_date, '%Y-%m-%d') as run_id,
        *
    from {{ source('silver_input', 'stops') }}
)

select
    run_id || ':' || lpad(cast(seq as varchar), 3, '0') as run_stop_id,
    run_id,
    source,
    train_no,
    start_date,
    seq,
    upper(station_code) as station_code,
    station_name,
    distance_km,
    sched_arr,
    act_arr,
    sched_dep,
    act_dep,
    arr_delay_min,
    dep_delay_min,
    platform,
    is_origin,
    is_destination,
    -- day of the journey the train is scheduled at this stop (0 = start date); arrival if any, else departure
    date_diff('day', start_date, {{ ist_date('coalesce(sched_arr, sched_dep)') }}) as sched_day_offset,
    date_diff('minute', sched_arr, sched_dep) as sched_halt_min,
    date_diff('minute', act_arr, act_dep) as act_halt_min,
    (act_arr is not null or act_dep is not null) as has_actual
from stops
