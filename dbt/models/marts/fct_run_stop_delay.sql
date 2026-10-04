-- Gold: one row per run × stop with arrival/departure delays and the delay gained on the segment from the
-- previous stop. Rows of cancelled, incomplete, diverted and disrupted runs are kept but flagged:
-- only `is_delay_target` rows feed delay statistics and model targets (architecture doc §5.2).
with stops as (
    select * from {{ ref('stg_train_run_stop') }}
),

runs as (
    select run_id, run_month, run_state, is_disruption, is_delay_target_eligible
    from {{ ref('fct_run_summary') }}
)

select
    s.run_stop_id,
    s.run_id,
    s.source,
    s.train_no,
    s.start_date,
    r.run_month,
    s.seq,
    s.station_code,
    c.cluster_id,
    s.distance_km,
    s.sched_day_offset,
    s.sched_arr,
    s.act_arr,
    s.sched_dep,
    s.act_dep,
    s.arr_delay_min,
    s.dep_delay_min,
    s.sched_halt_min,
    s.act_halt_min,
    s.is_origin,
    s.is_destination,
    lag(s.station_code) over w as prev_station_code,
    date_diff('minute', lag(s.sched_dep) over w, s.sched_arr) as sched_segment_min,
    date_diff('minute', lag(s.act_dep) over w, s.act_arr) as act_segment_min,
    -- delay gained (positive) or recovered (negative) between leaving the previous stop and arriving here
    s.arr_delay_min - lag(s.dep_delay_min) over w as segment_delay_gain_min,
    r.run_state,
    r.is_disruption,
    (
        r.is_delay_target_eligible
        and not s.is_origin
        and s.arr_delay_min is not null
    ) as is_delay_target
from stops as s
inner join runs as r using (run_id)
left join {{ ref('seed_station_cluster') }} as c using (station_code)
window w as (partition by s.run_id order by s.seq)
