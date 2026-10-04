-- Gold: one row per attempted run. Origin departure delay, final arrival delay, journey time actual vs scheduled,
-- and a run_state that decides whether the run may feed delay targets.
--
-- run_state:
--   complete    origin departure and destination arrival both reported
--   incomplete  fetched, but the origin departure or destination arrival has no actual time
--   cancelled   the payload says the run was cancelled
--   diverted    the last reported stop is not the scheduled destination (diverted or short-terminated)
--   not_found   never fetched successfully; the provider had no history (not run, cancelled, or not yet available)
--   fetch_error never fetched successfully because of HTTP/transport errors
--   unparseable fetched, but the payload could not be parsed
with runs as (
    select * from {{ ref('stg_train_run') }}
),

stops as (
    select * from {{ ref('stg_train_run_stop') }}
),

per_run as (
    select
        run_id,
        count(*) as n_stops,
        count(*) filter (where has_actual) as n_stops_with_actual,
        max(station_code) filter (where is_origin) as first_station_code,
        max(sched_dep) filter (where is_origin) as sched_departure,
        max(act_dep) filter (where is_origin) as act_departure,
        max(dep_delay_min) filter (where is_origin) as origin_dep_delay_min,
        max(station_code) filter (where is_destination) as last_station_code,
        max(sched_arr) filter (where is_destination) as sched_arrival,
        max(act_arr) filter (where is_destination) as act_arrival,
        max(arr_delay_min) filter (where is_destination) as final_arr_delay_min,
        max(distance_km) as route_km,
        max(arr_delay_min) as max_arr_delay_min
    from stops
    group by run_id
),

joined as (
    select
        r.run_id,
        r.source,
        r.train_no,
        r.train_name,
        r.start_date,
        cast(date_trunc('month', r.start_date) as date) as run_month,
        r.fetch_status,
        r.n_attempts,
        r.fetched_at,
        coalesce(p.first_station_code, r.origin_code) as origin_code,
        coalesce(r.destination_code, p.last_station_code) as destination_code,
        p.last_station_code,
        p.n_stops,
        p.n_stops_with_actual,
        p.route_km,
        p.sched_departure,
        p.act_departure,
        p.origin_dep_delay_min,
        p.sched_arrival,
        p.act_arrival,
        p.final_arr_delay_min,
        p.max_arr_delay_min,
        date_diff('minute', p.sched_departure, p.sched_arrival) as sched_journey_min,
        date_diff('minute', p.act_departure, p.act_arrival) as act_journey_min,
        case
            when r.fetch_status = 'not_found' then 'not_found'
            when r.fetch_status <> 'ok' then 'fetch_error'
            when not r.parse_ok or p.run_id is null then 'unparseable'
            when r.is_cancelled then 'cancelled'
            when r.destination_code is not null and p.last_station_code <> r.destination_code then 'diverted'
            when p.act_departure is null or p.act_arrival is null then 'incomplete'
            else 'complete'
        end as run_state
    from runs as r
    left join per_run as p using (run_id)
)

select
    *,
    act_journey_min - sched_journey_min as journey_overrun_min,
    coalesce(max_arr_delay_min > {{ var('delay_outlier_min') }}, false) as is_disruption,
    run_state = 'complete' and not coalesce(max_arr_delay_min > {{ var('delay_outlier_min') }}, false)
        as is_delay_target_eligible
from joined
