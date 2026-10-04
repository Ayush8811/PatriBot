-- Gold: trains seen by the collector, with their most recent name and route endpoints. (A slowly changing
-- dimension with timetable attributes comes with the schedule source; this is the running-data view.)
with runs as (
    select * from {{ ref('fct_run_summary') }}
)

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
from runs
group by train_no
