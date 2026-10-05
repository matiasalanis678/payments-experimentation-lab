-- One row per (experiment, assigned customer). Analysis population = is_exposed customers only.
with assignments as (
    select * from {{ ref('stg_assignments') }}
),

exposure as (
    select * from {{ ref('int_customer_exposure') }}
)

select
    assignments.experiment_id,
    assignments.customer_id,
    assignments.variant,
    assignments.assigned_at,
    exposure.first_exposure_at,
    exposure.first_exposure_at is not null as is_exposed,
    coalesce(exposure.experiment_sessions, 0) as experiment_sessions,
    coalesce(exposure.pre_period_sessions, 0) as pre_period_sessions,
    coalesce(exposure.pre_period_successful_sessions, 0) as pre_period_successful_sessions
from assignments
left join exposure on exposure.customer_id = assignments.customer_id
where assignments.experiment_id = '{{ var("experiment_id") }}'
