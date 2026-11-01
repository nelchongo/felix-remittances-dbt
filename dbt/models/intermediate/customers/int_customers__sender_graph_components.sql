-- Q5 label. One row per sender with its cluster: the connected component of the user ↔ beneficiary
-- graph (two senders are linked when they send to the same beneficiary). Recursive CTE, fine at this
-- scale (see DESIGN §17). cluster_id = smallest user_id in the component.
--   cluster_type: individual (1 sender) | household (2+ senders) | high_fan_in (a beneficiary in the
--   component receives from >= var('mule_min_senders') senders: AML review).
with recursive

receipts as (
    select * from {{ ref('stg_felix_backend__receipts') }}
),

edges as (
    select distinct
        user_id,
        beneficiary_id
    from receipts
    where user_id is not null and beneficiary_id is not null
),

user_links as (
    select distinct
        edges.user_id,
        linked.user_id as linked_user_id
    from edges
    inner join edges as linked on edges.beneficiary_id = linked.beneficiary_id
),

reachable (user_id, reached_user_id) as (
    select
        user_id,
        linked_user_id
    from user_links
    union
    select
        reachable.user_id,
        user_links.linked_user_id
    from reachable
    inner join user_links on reachable.reached_user_id = user_links.user_id
),

components as (
    select
        user_id,
        min(reached_user_id) as cluster_id
    from reachable
    group by user_id
),

beneficiary_fan_in as (
    select
        beneficiary_id,
        count(distinct user_id) as n_senders
    from edges
    group by beneficiary_id
),

cluster_stats as (
    select
        components.cluster_id,
        count(distinct components.user_id) as cluster_n_users,
        count(distinct edges.beneficiary_id) as cluster_n_beneficiaries,
        max(beneficiary_fan_in.n_senders) as cluster_max_senders_per_beneficiary
    from components
    inner join edges on components.user_id = edges.user_id
    inner join beneficiary_fan_in on edges.beneficiary_id = beneficiary_fan_in.beneficiary_id
    group by components.cluster_id
),

final as (
    select
        components.user_id,
        components.cluster_id,
        case
            when cluster_stats.cluster_max_senders_per_beneficiary >= {{ var('mule_min_senders') }} then 'high_fan_in'
            when cluster_stats.cluster_n_users > 1 then 'household'
            else 'individual'
        end as cluster_type,
        cast(cluster_stats.cluster_n_users as integer) as cluster_n_users,
        cast(cluster_stats.cluster_n_beneficiaries as integer) as cluster_n_beneficiaries,
        cast(cluster_stats.cluster_max_senders_per_beneficiary as integer) as cluster_max_senders_per_beneficiary
    from components
    inner join cluster_stats on components.cluster_id = cluster_stats.cluster_id
)

select * from final
