-- Silver: one row per train with a cached timetable. Running days are at the ORIGIN (MON..SUN); classes are the
-- reserved classes listed by station timetables (empty when unknown).
select
    source,
    train_no,
    nullif(trim(train_name), '') as train_name,
    nullif(trim(train_type), '') as train_type_raw,
    train_type_detail,
    train_type_display,
    upper(origin_code) as origin_code,
    upper(destination_code) as destination_code,
    dep_time,
    arr_time,
    travel_minutes,
    array_to_string(running_days, ',') as running_days,
    len(running_days) as n_running_days,
    array_to_string(classes, ',') as classes,
    exclusion_reason,
    exclusion_reason is null as is_reserved,
    n_stops,
    fetched_at
from {{ source('silver_input', 'train_info') }}
