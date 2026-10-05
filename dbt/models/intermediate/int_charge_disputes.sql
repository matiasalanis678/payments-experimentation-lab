-- One row per charge with its dispute (if any), lag, and maturity flags.
-- Two vantage points: as of analysis_date (the final read) and as of experiment end (the early read).
-- A charge is matured once dispute_maturity_days have passed, so its dispute outcome is (nearly) final.
with charges as (
    select charge_id, created_at, is_captured from {{ ref('stg_charges') }}
),

disputes as (
    select * from {{ ref('stg_disputes') }}
)

select
    charges.charge_id,
    charges.created_at as charge_created_at,
    disputes.dispute_id,
    disputes.created_at as dispute_created_at,
    disputes.reason as dispute_reason,
    disputes.status as dispute_status,
    disputes.amount_minor as dispute_amount_minor,
    date_diff('second', charges.created_at, disputes.created_at) / 86400.0 as dispute_lag_days,

    disputes.dispute_id is not null
        and disputes.created_at < {{ analysis_cutoff_ts() }} as is_disputed,
    charges.created_at + to_days({{ var('dispute_maturity_days') }})
        <= {{ analysis_cutoff_ts() }} as is_matured,

    disputes.dispute_id is not null
        and disputes.created_at < {{ experiment_end_ts() }} as is_disputed_at_experiment_end,
    charges.created_at + to_days({{ var('dispute_maturity_days') }})
        <= {{ experiment_end_ts() }} as is_matured_at_experiment_end
from charges
left join disputes on disputes.charge_id = charges.charge_id
