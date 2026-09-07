# Resume wording

Your original bullet:

> Retail Revenue & Retention Analytics (Power BI and SQL)
> Addressed revenue leakage and high customer drop-off by building an end-to-end data
> pipeline to identify high-value customer segments and optimize retention strategies.
> Analyzed 60,000+ transactions across 7 SQL tables, building an interactive Power BI
> dashboard to track €2.4M total revenue and ~20% profit margins. Used DAX and SQL
> cohort analysis to discover that the top 30% of customers drive 60% of total revenue,
> enabling targeted marketing campaigns to boost repeat sales.

## What survives contact with the real data

| Claim | Status against the real dataset |
|---|---|
| 60,000+ transactions | ✅ **62,316** |
| 7 SQL tables | ✅ built as a star schema |
| €2.4M total revenue | ✅ **€2,428,192** |
| ~20% profit margins | ⚠️ **modelled**, not measured — the source file has no cost column |
| Top 30% of customers drive 60% of revenue | ❌ the real figure is **85.7%** |

Four of the five hold. The concentration claim is the one that has to change — and it
changes in your favour, because the real number is more striking.

## Recommended rewrite

The cleanest fix is to move the cut-off from the top 30% to the top 10%, which lands
almost exactly on "60%" and is measured, not modelled:

> **Retail Revenue & Retention Analytics (Power BI, SQL, Python)**
> Addressed revenue leakage and high customer drop-off by building an end-to-end
> pipeline over a public UCI retail dataset — profiling and cleaning 1M+ raw rows
> (34k duplicates, 243k records missing customer IDs, 19k cancellation invoices) into a
> 7-table SQL star schema. Analyzed **62,000+ transactions** in an interactive Power BI
> dashboard tracking **€2.4M revenue** and **~20% margin**. Used DAX and SQL cohort
> analysis to show the **top 10% of customers drive 66% of revenue** and that one-time
> buyers — 30% of the base — contribute only 5%, enabling a targeted win-back campaign
> for 13 lapsed high-value accounts worth €89k.

## If you prefer to keep "top 30%"

Then state the real number, which is a stronger claim anyway:

> ...cohort analysis to discover that the **top 30% of customers drive 86% of revenue**,
> concentrating retention spend on 152 accounts.

## Interview notes

Be ready for these — they are the questions the bullet invites.

**"Where did the data come from?"**
UCI Machine Learning Repository, "Online Retail II" — a real UK online retailer,
Dec 2009 – Dec 2011, ~1.07M rows. I scoped it to the non-UK export business.

**"Why did you exclude the UK and Ireland?"**
The UK is 91% of rows and would swamp the export segment. Ireland was three accounts
generating 21.5% of export revenue — a wholesale relationship, not retail behaviour,
so it distorted every per-customer metric. Both exclusions are logged in the pipeline.

**"How did you get profit margin if there's no cost column?"**
I didn't measure it — I modelled it. Each derived category gets a relative gross margin
and the set is scaled so the blended margin is 20%. Say this plainly; claiming it was
measured is the one thing that would actually hurt you.

**"How do you know the numbers are right?"**
`verify_sql.py` runs every query against SQLite in ~2 seconds, and
`03_data_quality_checks.sql` has 10 checks that must return zero rows. It caught two
real bugs: a cohort join that inflated the denominator so retention read 0.2%, and 128
invoices listing the same product twice.

**"What would you do differently?"**
The cost model is the weak point, and 508 customers makes individual cohort cells noisy
(median cohort size 20). I'd run the UK segment alongside it for a smoother retention
matrix.
