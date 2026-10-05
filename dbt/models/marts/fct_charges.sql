-- One row per charge (payment attempt) with authorization outcome, USD amounts, and dispute maturity.
with charges as (
    select * from {{ ref('stg_charges') }}
),

sessions as (
    select checkout_session_id, payment_intent_id, period, experiment_week from {{ ref('int_session_outcomes') }}
),

disputes as (
    select * from {{ ref('int_charge_disputes') }}
),

fx as (
    select * from {{ ref('stg_fx_rates') }}
),

experiment as (
    select * from {{ ref('dim_experiment') }}
),

customers as (
    select * from {{ ref('dim_customers') }}
)

select
    charges.charge_id,
    sessions.checkout_session_id,
    charges.customer_id,
    charges.created_at,
    cast(charges.created_at as date) as charge_date,
    sessions.period,
    sessions.experiment_week,
    experiment.experiment_id,
    experiment.variant,
    experiment.is_exposed,
    customers.country,
    charges.card_brand,
    charges.card_funding,
    charges.card_country,
    customers.is_returning,
    customers.account_age_band,
    customers.risk_score_band,
    charges.status,
    charges.is_authorized,
    charges.is_captured,
    charges.outcome_type,
    charges.outcome_reason,
    charges.outcome_network_status,
    charges.outcome_risk_level,
    charges.failure_code,
    charges.cvc_check,
    charges.currency,
    {{ minor_to_usd('charges.amount_minor', 'fx.minor_unit_exponent', 'fx.usd_per_unit') }} as amount_usd,
    {{ minor_to_usd('charges.amount_captured_minor', 'fx.minor_unit_exponent', 'fx.usd_per_unit') }}
        as captured_amount_usd,
    disputes.dispute_id,
    disputes.dispute_created_at,
    disputes.dispute_reason,
    disputes.dispute_status,
    disputes.dispute_lag_days,
    disputes.is_disputed,
    disputes.is_matured,
    disputes.is_disputed_at_experiment_end,
    disputes.is_matured_at_experiment_end,
    case
        when disputes.is_disputed
            then {{ minor_to_usd('disputes.dispute_amount_minor', 'fx.minor_unit_exponent', 'fx.usd_per_unit') }}
        else 0
    end as disputed_amount_usd
from charges
inner join sessions on sessions.payment_intent_id = charges.payment_intent_id
left join disputes on disputes.charge_id = charges.charge_id
left join fx on fx.currency = charges.currency
left join experiment on experiment.customer_id = charges.customer_id
left join customers on customers.customer_id = charges.customer_id
