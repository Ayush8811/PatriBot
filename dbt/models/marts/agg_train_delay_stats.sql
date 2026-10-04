-- Gold: final-arrival delay per train, per run month ('YYYY-MM') and over all months ('all'). The planner scales it
-- by the fraction of the route travelled when a station has too little history of its own.
with runs as (
    select train_no, strftime(run_month, '%Y-%m') as period, final_arr_delay_min, route_km
    from {{ ref('fct_run_summary') }}
    where is_delay_target_eligible and final_arr_delay_min is not null
),

periods as (
    select * from runs
    union all
    select train_no, 'all' as period, final_arr_delay_min, route_km from runs
)

select
    train_no || ':' || period as train_delay_stat_id,
    train_no,
    period,
    count(*) as n_runs,
    round(avg(final_arr_delay_min), 1) as mean_final_delay_min,
    quantile_cont(final_arr_delay_min, 0.5) as p50_final_delay_min,
    quantile_cont(final_arr_delay_min, 0.9) as p90_final_delay_min,
    round(100.0 * avg(case when final_arr_delay_min <= {{ var('on_time_threshold_min') }} then 1 else 0 end), 1)
        as pct_within_30min,
    round(avg(route_km), 0) as route_km
from periods
group by train_no, period
