-- In-window sessions have weeks 1 to 8; other sessions have no week.
select checkout_session_id
from {{ ref('fct_checkout_sessions') }}
where (period = 'experiment' and (experiment_week is null or experiment_week not between 1 and 8))
    or (period <> 'experiment' and experiment_week is not null)
