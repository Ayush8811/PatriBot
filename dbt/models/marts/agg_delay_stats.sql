-- Gold: arrival-delay distribution per train × station × month, from delay-target rows only.
-- This is baseline B2 of the ETA model (architecture doc §6) and feeds the planner until the ML model ships.
with targets as (
    select * from {{ ref('fct_run_stop_delay') }}
    where is_delay_target
)

select
    train_no || ':' || station_code || ':' || strftime(run_month, '%Y-%m') as delay_stat_id,
    train_no,
    station_code,
    run_month,
    count(*) as n_runs,
    round(avg(arr_delay_min), 1) as mean_arr_delay_min,
    quantile_cont(arr_delay_min, 0.5) as p50_arr_delay_min,
    quantile_cont(arr_delay_min, 0.9) as p90_arr_delay_min,
    min(arr_delay_min) as min_arr_delay_min,
    max(arr_delay_min) as max_arr_delay_min,
    round(100.0 * avg(case when arr_delay_min <= {{ var('on_time_threshold_min') }} then 1 else 0 end), 1)
        as pct_within_30min,
    round(avg(dep_delay_min), 1) as mean_dep_delay_min,
    round(avg(distance_km), 0) as distance_km,
    max(seq) as max_seq,
    string_agg(distinct source, ',' order by source) as sources
from targets
group by train_no, station_code, run_month
