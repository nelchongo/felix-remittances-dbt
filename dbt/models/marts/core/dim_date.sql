-- Calendar dimension, one row per day 2024-01-01 → 2027-12-31. Also the MetricFlow time spine.
-- Holiday flags: US federal holidays (where senders live) and the remittance peaks planted in the data
-- (December and the run-up to Mexican Mother's Day, May 1–10).
with

spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2024-01-01' as date)",
        end_date="cast('2028-01-01' as date)"
    ) }}
),

days as (
    select
        cast(date_day as date) as date_day,
        extract(year from date_day) as year_number,
        extract(month from date_day) as month_number,
        extract(day from date_day) as day_of_month,
        isodow(date_day) as iso_day_of_week
    from spine
),

holidays as (
    select
        *,
        case
            when month_number = 1 and day_of_month = 1 then 'New Year''s Day'
            when month_number = 1 and iso_day_of_week = 1 and day_of_month between 15 and 21 then 'Martin Luther King Jr. Day'
            when month_number = 2 and iso_day_of_week = 1 and day_of_month between 15 and 21 then 'Presidents'' Day'
            when month_number = 5 and iso_day_of_week = 1 and day_of_month >= 25 then 'Memorial Day'
            when month_number = 6 and day_of_month = 19 then 'Juneteenth'
            when month_number = 7 and day_of_month = 4 then 'Independence Day'
            when month_number = 9 and iso_day_of_week = 1 and day_of_month <= 7 then 'Labor Day'
            when month_number = 10 and iso_day_of_week = 1 and day_of_month between 8 and 14 then 'Columbus Day'
            when month_number = 11 and day_of_month = 11 then 'Veterans Day'
            when month_number = 11 and iso_day_of_week = 4 and day_of_month between 22 and 28 then 'Thanksgiving'
            when month_number = 12 and day_of_month = 25 then 'Christmas Day'
        end as us_holiday_name
    from days
),

final as (
    select
        date_day,
        cast(strftime(date_day, '%Y%m%d') as integer) as date_sk,
        cast(year_number as integer) as year_number,
        cast(extract(quarter from date_day) as integer) as quarter_number,
        cast(month_number as integer) as month_number,
        strftime(date_day, '%B') as month_name,
        cast(date_trunc('month', date_day) as date) as month_start_date,
        cast(date_trunc('quarter', date_day) as date) as quarter_start_date,
        cast(date_trunc('week', date_day) as date) as week_start_date,
        cast(day_of_month as integer) as day_of_month,
        cast(iso_day_of_week as integer) as iso_day_of_week,
        strftime(date_day, '%A') as day_name,
        iso_day_of_week in (6, 7) as is_weekend,
        us_holiday_name,
        us_holiday_name is not null as is_us_holiday,
        month_number = 5 and day_of_month = 10 as is_mexican_mothers_day,
        month_number = 12 or (month_number = 5 and day_of_month <= 10) as is_remittance_peak
    from holidays
)

select * from final
