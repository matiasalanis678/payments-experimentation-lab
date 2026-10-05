-- Disputes arrive 7 to 60 days after the charge, and only on captured charges.
select charge_id
from {{ ref('fct_charges') }}
where dispute_id is not null
    and (dispute_lag_days < 7 or dispute_lag_days > {{ var('dispute_maturity_days') }} or not is_captured)
