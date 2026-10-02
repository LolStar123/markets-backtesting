# Research archive design

## Current route

The public index redirects to the combined quant research workbench. Keep that URL and its fallback link intact. `legacy.html` restores the standalone browser interface from the commit immediately before the redirect, with its original stylesheet in `legacy.css`; a visible notice links to the current application.

## What the reader sees

The README leads with the current repository and app, then separates the rolling browser experiment from the recorded 50-signal Python run. Each has an actual entry command, inputs, output and checks. Counts in the archived summary come from the committed CSV, including non-positive rows; avoid promoting a historical ranking as a forecast.

## Retained interface

The original browser uses charcoal and muted green, system sans-serif text, monospace numerical controls and a plot beside the training/test settings. The archive table remains available through its tab. Retaining those styles preserves a usable historical reference rather than pretending it is the newly combined application.

## Verification

Synthetic Python checks exercise lag and costs without invoking a price provider. Node checks use the committed cache and perturb unseen prices. The headless browser audit visits the redirect and `/legacy.html`, reruns a historical experiment, opens the archive, and checks desktop and mobile overflow. Screenshots go under ignored `output/`.

## Editorial check

Named emotions: none. Unsupported walk-forward claims: corrected; the 50-rule run and rolling browser selection are separate. Rejected phrases: "uncover hidden alpha", "institutional-grade performance", "powerful insights". Personal costs and sensory quotas do not fit this guide and were not invented. Unresolved: price-cache adjustment provenance and complete provider reconstruction have not been independently verified.
