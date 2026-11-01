-- Q5. Sender clusters: connected components of the user ↔ beneficiary graph, with a type and their size.
-- Linked to senders through dim_users.cluster_id and bridge_user_beneficiary.cluster_sk.
with

components as (
    select * from {{ ref('int_customers__sender_graph_components') }}
),

receipts as (
    select * from {{ ref('stg_felix_backend__receipts') }}
),

first_transfers as (
    select
        components.cluster_id,
        min(receipts.created_at) as first_transfer_at
    from components
    inner join receipts on components.user_id = receipts.user_id
    group by components.cluster_id
),

clusters as (
    select
        components.cluster_id,
        any_value(components.cluster_type) as cluster_type,
        any_value(components.cluster_n_users) as n_users,
        any_value(components.cluster_n_beneficiaries) as n_beneficiaries,
        any_value(components.cluster_max_senders_per_beneficiary) as max_senders_per_beneficiary,
        any_value(first_transfers.first_transfer_at) as first_transfer_at
    from components
    left join first_transfers on components.cluster_id = first_transfers.cluster_id
    group by components.cluster_id
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['cluster_id']) }} as cluster_sk,
        cluster_id,
        cluster_type,
        n_users,
        n_beneficiaries,
        max_senders_per_beneficiary,
        first_transfer_at
    from clusters
)

select * from final
union all by name
{{ unknown_member(model.columns) }}
