# Research data provenance

`examples/portfolio/data/spy.json`: date and close columns from the existing
`quant/ibkr_data/SPY_1day.csv` research cache. 5,351 rows, 2005-01-03 to 2026-04-10.
The file location is known; upstream adjustment provenance has not been independently verified.
No generated prices are used.

`research.json`: exact rows from the public `quantihack_alt_data_50_results.csv`.
The original Python implementation and cited papers remain in the repository.

The browser walk-forward moving-average test is a separate executable example, not a port
of all 50 strategies. Selection uses only the preceding training period; exposure uses the
previous close. One-sided turnover incurs the selected fee. Open final positions are marked
to market without a forced liquidation fee. Taxes and cash interest are excluded.
