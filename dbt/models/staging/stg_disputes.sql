select
    id as dispute_id,
    charge as charge_id,
    {{ epoch_to_timestamp('created') }} as created_at,
    amount as amount_minor,
    currency,
    reason,
    status
from {{ source('stripe', 'disputes') }}
