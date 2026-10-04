-- Gold: corridor membership (architecture doc §3.2, D10), one row per train × corridor.
-- The rule is applied in Python by patribot.watchlist.membership (the same functions that build the collector's
-- watchlist, so the two can never disagree) and lands here per corridor PATH; this model keeps the widest match per
-- train × corridor and lists every path the train matched.
with paths as (
    select * from {{ source('silver_input', 'train_corridor') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by train_no, corridor_id order by segments desc, coalesce(km, 0) desc, path_name
        ) as rn,
        string_agg(path_name, ',' order by path_name) over (partition by train_no, corridor_id) as path_names
    from paths
)

select
    r.train_no || ':' || r.corridor_id as train_corridor_id,
    r.train_no,
    r.corridor_id,
    c.corridor_name,
    r.path_name as best_path_name,
    r.path_names,
    r.from_code,
    r.to_code,
    r.segments,
    r.km,
    r.direction,
    -- the widest matched halts lie in the corridor's two end clusters (an end-to-end train)
    coalesce(
        r.direction = 'AB' and fc.cluster_id = c.cluster_a and tc.cluster_id = c.cluster_b
        or r.direction = 'BA' and fc.cluster_id = c.cluster_b and tc.cluster_id = c.cluster_a,
        false
    ) as serves_both_ends
from ranked as r
inner join {{ ref('seed_corridor') }} as c using (corridor_id)
left join {{ ref('seed_station_cluster') }} as fc on fc.station_code = r.from_code
left join {{ ref('seed_station_cluster') }} as tc on tc.station_code = r.to_code
where r.rn = 1
