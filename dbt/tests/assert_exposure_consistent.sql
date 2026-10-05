-- Exposed customers were bucketed no later than their first in-window session, which falls in the window.
select customer_id
from {{ ref('dim_experiment') }}
where is_exposed
    and (
        assigned_at > first_exposure_at
        or first_exposure_at < {{ experiment_start_ts() }}
        or first_exposure_at >= {{ experiment_end_ts() }}
    )
