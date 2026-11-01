-- Factless bridge between senders and beneficiaries: one row per user × beneficiary pair that has at
-- least one remittance. Carries the pair's transfer count and volume and the sender's cluster (Q5).
-- Keys point to the current versions of the SCD2 dimensions.
with

remittances as (
    select * from {{ ref('int_remittances__joined') }}
),

clusters as (
    select * from {{ ref('int_customers__sender_graph_components') }}
),

users as (
    select * from {{ ref('dim_users') }}
    where is_current
),

beneficiaries as (
    select * from {{ ref('dim_beneficiaries') }}
    where is_current
),

sender_clusters as (
    select * from {{ ref('dim_sender_clusters') }}
),

corridors as (
    select * from {{ ref('dim_corridors') }}
),

pairs as (
    select
        user_id,
        beneficiary_id,
        any_value(destination_country) as destination_country,
        count(*) as n_transfers,
        sum(send_amount_usd) as volume_usd,
        min(receipt_created_at) as first_sent_at,
        max(receipt_created_at) as last_sent_at
    from remittances
    group by user_id, beneficiary_id
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['pairs.user_id', 'pairs.beneficiary_id']) }} as user_beneficiary_id,
        coalesce(users.user_sk, '-1') as user_sk,
        coalesce(beneficiaries.beneficiary_sk, '-1') as beneficiary_sk,
        coalesce(sender_clusters.cluster_sk, '-1') as cluster_sk,
        coalesce(corridors.corridor_sk, '-1') as corridor_sk,
        pairs.user_id,
        pairs.beneficiary_id,
        clusters.cluster_id,
        clusters.cluster_type,
        pairs.destination_country,
        cast(pairs.n_transfers as integer) as n_transfers,
        cast(pairs.volume_usd as decimal(18, 2)) as volume_usd,
        pairs.first_sent_at,
        pairs.last_sent_at
    from pairs
    left join clusters on pairs.user_id = clusters.user_id
    left join users on pairs.user_id = users.user_id
    left join beneficiaries on pairs.beneficiary_id = beneficiaries.beneficiary_id
    left join sender_clusters on clusters.cluster_id = sender_clusters.cluster_id
    left join corridors on pairs.destination_country = corridors.country_code
)

select * from final
