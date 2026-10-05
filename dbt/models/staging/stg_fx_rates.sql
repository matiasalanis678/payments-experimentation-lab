select
    currency,
    exponent as minor_unit_exponent,
    usd_per_unit
from {{ source('stripe', 'fx_rates') }}
