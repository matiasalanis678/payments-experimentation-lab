select
    id as customer_id,
    {{ epoch_to_timestamp('created') }} as created_at,
    address_country as country,
    default_card_brand as card_brand,
    default_card_funding as card_funding
from {{ source('stripe', 'customers') }}
