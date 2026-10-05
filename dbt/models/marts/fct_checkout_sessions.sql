-- One row per checkout session (pre-period and experiment window) with funnel flags and segments.
with sessions as (
    select * from {{ ref('int_session_outcomes') }}
),

experiment as (
    select * from {{ ref('dim_experiment') }}
),

customers as (
    select * from {{ ref('dim_customers') }}
)

select
    sessions.checkout_session_id,
    sessions.customer_id,
    sessions.charge_id,
    sessions.created_at,
    cast(sessions.created_at as date) as session_date,
    sessions.period,
    sessions.experiment_week,
    experiment.experiment_id,
    experiment.variant,
    experiment.is_exposed,
    customers.country,
    customers.card_brand,
    customers.card_funding,
    customers.is_returning,
    customers.account_age_band,
    customers.risk_score_band,
    sessions.is_attempted,
    sessions.is_authorized,
    sessions.is_succeeded,
    sessions.currency,
    sessions.amount_total_usd,
    sessions.succeeded_amount_usd
from sessions
left join experiment on experiment.customer_id = sessions.customer_id
left join customers on customers.customer_id = sessions.customer_id
