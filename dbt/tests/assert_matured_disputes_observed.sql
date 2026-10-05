-- Sanity check on maturity: a matured charge's dispute (if any) must already be observed at analysis_date.
select charge_id
from {{ ref('fct_charges') }}
where is_matured and dispute_id is not null and not is_disputed
