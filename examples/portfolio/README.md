# Preserved market backtesting experiment

**[Current combined workbench](https://lolstar123.github.io/quant-research-scraper/backtesting/).** The public index redirects there. For the retained standalone source, run `python -m http.server 8000 --bind 127.0.0.1 --directory examples/portfolio` from the repository root, then open **http://127.0.0.1:8000/legacy.html**.

Choose a training window, test window and trading cost. The browser selects a moving-average rule using past data, freezes it for the next window, then compares after-cost returns with buy-and-hold. Export the out-of-sample returns or browse the separate 50-strategy research archive.

The experiment uses 5,351 historical SPY daily closes. Upstream adjustment provenance remains unverified. See [data provenance](../../PROVENANCE.md) for dates and model boundaries and the [repository guide](../../README.md) for dependencies and offline checks.

Run `node --test examples/portfolio/model.test.mjs` for calculation checks and `python tools/browser_audit.py` for redirect, archived browser controls, file export and desktop/mobile layout checks.
