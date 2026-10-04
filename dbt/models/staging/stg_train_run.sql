-- Silver: one row per run key the collector attempted, with the fetch outcome and the payload header.
select
    source || ':' || train_no || ':' || strftime(start_date, '%Y-%m-%d') as run_id,
    source,
    train_no,
    start_date,
    fetch_status,
    http_status,
    error,
    n_attempts,
    first_fetched_at,
    fetched_at,
    bronze_file,
    parse_ok,
    nullif(trim(train_name), '') as train_name,
    journey_date,
    upper(nullif(trim(origin_code), '')) as origin_code,
    upper(nullif(trim(destination_code), '')) as destination_code,
    n_stations_raw,
    n_stations_parsed,
    coalesce(is_cancelled, false) as is_cancelled,
    last_update
from {{ source('silver_input', 'runs') }}
