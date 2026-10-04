-- Gold: one row per calendar date (2026–2027) with day-of-week and calendar flags (BRD FR-14) from the hand-kept
-- seed calendar_events: national holidays, festival travel-rush windows and the North India fog season.
-- Lunar festival dates are marked approximate in the seed. Weather is not covered yet (docs/phase2/planner-api.md).
with days as (
    select cast(d as date) as date_day
    from range(date '2026-01-01', date '2028-01-01', interval 1 day) as t(d)
),

events as (
    select * from {{ ref('calendar_events') }}
),

flagged as (
    select
        d.date_day,
        string_agg(e.event_name, '; ' order by e.start_date) filter (where e.kind = 'national_holiday')
            as holiday_names,
        string_agg(e.event_name, '; ' order by e.start_date) filter (where e.kind = 'festival_window')
            as festival_names,
        string_agg(e.corridors, '|') filter (where e.kind = 'fog_season') as fog_corridors,
        bool_or(e.approximate) filter (where e.kind <> 'national_holiday') as any_approximate,
        bool_or(e.kind = 'festival_window' and d.date_day = e.peak_date) as is_festival_peak
    from days as d
    left join events as e on d.date_day between e.start_date and e.end_date
    group by d.date_day
)

select
    date_day,
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    strftime(date_day, '%Y-%m') as year_month,
    extract(day from date_day) as day_of_month,
    isodow(date_day) as dow,  -- 1 = Monday … 7 = Sunday
    upper(strftime(date_day, '%a')) as dow_name,  -- MON … SUN, as in running_days
    isodow(date_day) >= 6 as is_weekend,
    holiday_names is not null as is_national_holiday,
    holiday_names,
    festival_names is not null as is_festival_window,
    coalesce(is_festival_peak, false) as is_festival_peak,
    festival_names,
    fog_corridors is not null as is_fog_season,  -- North India corridors only; see fog_corridors
    fog_corridors,
    coalesce(any_approximate, false) as any_approximate
from flagged
