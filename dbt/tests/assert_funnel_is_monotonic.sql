-- succeeded implies authorized implies attempted, for every session.
select checkout_session_id
from {{ ref('int_session_outcomes') }}
where (is_succeeded and not is_authorized)
    or (is_authorized and not is_attempted)
