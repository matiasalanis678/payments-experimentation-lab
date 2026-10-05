-- Joins in the marts must not add or drop rows relative to staging.
select 'fct_checkout_sessions' as model
where (select count(*) from {{ ref('fct_checkout_sessions') }})
    <> (select count(*) from {{ ref('stg_checkout_sessions') }})
union all
select 'fct_charges'
where (select count(*) from {{ ref('fct_charges') }}) <> (select count(*) from {{ ref('stg_charges') }})
union all
select 'dim_customers'
where (select count(*) from {{ ref('dim_customers') }}) <> (select count(*) from {{ ref('stg_customers') }})
