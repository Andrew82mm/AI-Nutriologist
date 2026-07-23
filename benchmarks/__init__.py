"""Pipeline-quality benchmarks for the nutrition project.

Not an ML leaderboard — these quantify the data-analytics story «raw receipts →
clean data»: how much of the pipeline runs deterministically (for free) vs needs
a paid LLM call, how well parsed receipts reconcile against their printed total,
and how far LLM nutrition estimates drift from the trusted Скурихин dataset.

Run everything and regenerate the report card with:

    python -m benchmarks.run_all
"""
