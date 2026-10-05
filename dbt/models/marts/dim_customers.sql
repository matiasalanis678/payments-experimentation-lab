-- One row per customer with observable, pre-treatment attributes and a rule-based risk score.
-- The score uses only what a merchant sees at first checkout (account age, card funding, country);
-- it never uses outcomes, so it cannot be moved by the treatment.
with customers as (
    select * from {{ ref('stg_customers') }}
),

exposure as (
    select * from {{ ref('int_customer_exposure') }}
),

features as (
    select
        customers.customer_id,
        customers.created_at,
        customers.country,
        customers.card_brand,
        customers.card_funding,
        customers.created_at < {{ experiment_start_ts() }} as is_returning,
        date_diff(
            'day', customers.created_at, coalesce(exposure.first_exposure_at, {{ experiment_start_ts() }})
        ) as account_age_days_at_exposure
    from customers
    left join exposure on exposure.customer_id = customers.customer_id
),

scored as (
    select
        *,
        case
            when not is_returning then 'new'
            when account_age_days_at_exposure < 90 then '0-90d'
            when account_age_days_at_exposure < 365 then '90-365d'
            else '365d+'
        end as account_age_band,
        (case when account_age_days_at_exposure < 30 then 2 when account_age_days_at_exposure < 90 then 1 else 0 end)
        + (case when card_funding = 'prepaid' then 2 else 0 end)
        + (case when country in ('BR', 'MX') then 1 else 0 end) as risk_score
    from features
)

select
    *,
    case
        when risk_score = 0 then 'low'
        when risk_score <= 2 then 'medium'
        else 'high'
    end as risk_score_band
from scored
