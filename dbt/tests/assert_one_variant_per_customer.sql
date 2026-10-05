-- Every customer has exactly one variant in the experiment (no missing and no conflicting assignments).
select
    customers.customer_id,
    count(distinct assignments.variant) as n_variants
from {{ ref('stg_customers') }} as customers
left join {{ ref('stg_assignments') }} as assignments
    on assignments.customer_id = customers.customer_id
    and assignments.experiment_id = '{{ var("experiment_id") }}'
group by customers.customer_id
having count(distinct assignments.variant) <> 1
