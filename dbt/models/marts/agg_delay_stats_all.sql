-- Gold: arrival-delay distribution per train × station over ALL months (baseline B1). The planner uses it when the
-- month-specific row (agg_delay_stats, B2) has too few runs.
select
    train_no || ':' || station_code as delay_stat_id,
    train_no,
    station_code,
    count(*) as n_runs,
    round(avg(arr_delay_min), 1) as mean_arr_delay_min,
    quantile_cont(arr_delay_min, 0.5) as p50_arr_delay_min,
    quantile_cont(arr_delay_min, 0.9) as p90_arr_delay_min,
    round(100.0 * avg(case when arr_delay_min <= {{ var('on_time_threshold_min') }} then 1 else 0 end), 1)
        as pct_within_30min,
    round(avg(distance_km), 0) as distance_km,
    min(start_date) as first_start_date,
    max(start_date) as last_start_date
from {{ ref('fct_run_stop_delay') }}
where is_delay_target
group by train_no, station_code
