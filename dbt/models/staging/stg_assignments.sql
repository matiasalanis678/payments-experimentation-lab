select
    customer_id,
    experiment_id,
    variant,
    {{ epoch_to_timestamp('assigned_at') }} as assigned_at
from {{ source('stripe', 'experiment_assignments') }}
