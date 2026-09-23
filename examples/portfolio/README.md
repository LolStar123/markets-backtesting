# Market backtesting / walk-forward research

[Open the experiment](https://lolstar123.github.io/markets-backtesting/).

Choose a training window, test window and trading cost. The pipeline selects a moving-average rule using past data, freezes it for the next window, then compares its after-cost returns with buy-and-hold. Export the out-of-sample returns or browse the separate 50-strategy research archive.

The experiment uses 5,351 historical SPY daily closes. The upstream adjustment provenance remains unverified. See [data provenance](../../PROVENANCE.md) for dates and model boundaries.

Run `python -m http.server 8000 --directory examples/portfolio`, then open localhost:8000. Run `node --test examples/portfolio/model.test.mjs` and `python tools/browser_audit.py` to check the calculations and browser workflow.
