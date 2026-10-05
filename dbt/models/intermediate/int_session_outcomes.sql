-- One row per checkout session with its funnel outcome and experiment period.
with sessions as (
    select * from {{ ref('stg_checkout_sessions') }}
),

charges as (
    select * from {{ ref('stg_charges') }}
),

fx as (
    select * from {{ ref('stg_fx_rates') }}
)

select
    sessions.checkout_session_id,
    sessions.customer_id,
    sessions.payment_intent_id,
    sessions.created_at,
    case
        when sessions.created_at < {{ experiment_start_ts() }} then 'pre_period'
        when sessions.created_at < {{ experiment_end_ts() }} then 'experiment'
        else 'post_experiment'
    end as period,
    case
        when sessions.created_at >= {{ experiment_start_ts() }} and sessions.created_at < {{ experiment_end_ts() }}
            then date_diff('second', {{ experiment_start_ts() }}, sessions.created_at) // 604800 + 1
    end as experiment_week,
    charges.charge_id,
    charges.charge_id is not null as is_attempted,
    coalesce(charges.is_authorized, false) as is_authorized,
    coalesce(charges.is_captured, false) as is_succeeded,
    sessions.currency,
    {{ minor_to_usd('sessions.amount_total_minor', 'fx.minor_unit_exponent', 'fx.usd_per_unit') }} as amount_total_usd,
    case
        when charges.is_captured
            then {{ minor_to_usd('charges.amount_captured_minor', 'fx.minor_unit_exponent', 'fx.usd_per_unit') }}
        else 0
    end as succeeded_amount_usd
from sessions
left join charges on charges.payment_intent_id = sessions.payment_intent_id
left join fx on fx.currency = sessions.currency
