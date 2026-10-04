-- Gold: final-arrival delay of the corridor's member trains, per run month and over all months ('all').
-- The planner's last fallback before "no history" (a train with no runs of its own).
with runs as (
    select
        tc.corridor_id,
        strftime(r.run_month, '%Y-%m') as period,
        r.train_no,
        r.final_arr_delay_min
    from {{ ref('fct_run_summary') }} as r
    inner join {{ ref('dim_train_corridor') }} as tc using (train_no)
    where r.is_delay_target_eligible and r.final_arr_delay_min is not null
),

periods as (
    select * from runs
    union all
    select corridor_id, 'all' as period, train_no, final_arr_delay_min from runs
)

select
    corridor_id || ':' || period as corridor_delay_stat_id,
    corridor_id,
    period,
    count(*) as n_runs,
    count(distinct train_no) as n_trains,
    round(avg(final_arr_delay_min), 1) as mean_final_delay_min,
    quantile_cont(final_arr_delay_min, 0.5) as p50_final_delay_min,
    quantile_cont(final_arr_delay_min, 0.9) as p90_final_delay_min,
    round(100.0 * avg(case when final_arr_delay_min <= {{ var('on_time_threshold_min') }} then 1 else 0 end), 1)
        as pct_within_30min
from periods
group by corridor_id, period
