# Contributing

Keep changes small enough that their effect on comparability is clear.

1. Create a branch from `main`.
2. Add or change a signal as a deterministic function of the supplied data frames.
3. Keep the one-bar execution lag. Document any deliberate change to slippage, dates, metrics,
   ranking, or input symbols.
4. Run `python quantihack_alt_data_50.py`.
5. Check the generated CSV and chart, then explain material result changes in the pull request.

Do not commit credentials or licensed datasets. Optional local price files belong under
`ibkr_data/` and should remain untracked.
