select
    id as checkout_session_id,
    customer as customer_id,
    payment_intent as payment_intent_id,
    {{ epoch_to_timestamp('created') }} as created_at,
    {{ epoch_to_timestamp('expires_at') }} as expires_at,
    mode,
    status,
    payment_status,
    amount_total as amount_total_minor,
    currency
from {{ source('stripe', 'checkout_sessions') }}
