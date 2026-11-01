-- Q5. Sender clusters: connected components of the user ↔ beneficiary graph, with a type and their size.
-- Linked to senders through dim_users.cluster_id and bridge_user_beneficiary.cluster_sk.
with

components as (
    select * from {{ ref('int_customers__sender_graph_components') }}
),

clusters as (
    select
        cluster_id,
        any_value(cluster_type) as cluster_type,
        any_value(cluster_n_users) as n_users,
        any_value(cluster_n_beneficiaries) as n_beneficiaries,
        any_value(cluster_max_senders_per_beneficiary) as max_senders_per_beneficiary
    from components
    group by cluster_id
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['cluster_id']) }} as cluster_sk,
        cluster_id,
        cluster_type,
        n_users,
        n_beneficiaries,
        max_senders_per_beneficiary
    from clusters
)

select * from final
union all by name
{{ unknown_member(model.columns) }}
