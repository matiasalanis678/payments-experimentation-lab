-- One row per customer with at least one session: first exposure and pre-period activity (CUPED covariate).
select
    customer_id,
    min(created_at) filter (where period = 'experiment') as first_exposure_at,
    count(*) filter (where period = 'experiment') as experiment_sessions,
    count(*) filter (where period = 'pre_period') as pre_period_sessions,
    count(*) filter (where period = 'pre_period' and is_succeeded) as pre_period_successful_sessions
from {{ ref('int_session_outcomes') }}
group by customer_id
