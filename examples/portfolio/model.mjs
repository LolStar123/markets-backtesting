const prices = Array.from({ length: 260 }, (_, i) =>
  Number(
    (100 + Math.sin(i * 0.17) * 7 + Math.sin(i * 0.71) * 2 + i * 0.035).toFixed(
      3,
    ),
  ),
);
export const defaults = { train: 80, test: 30, costBps: 8, prices };
export const controls = [
  {
    key: "train",
    label: "Training observations",
    type: "number",
    min: 40,
    max: 180,
    step: 10,
  },
  {
    key: "test",
    label: "Test observations",
    type: "number",
    min: 10,
    max: 60,
    step: 5,
  },
  {
    key: "costBps",
    label: "Cost per side (basis points)",
    type: "number",
    min: 0,
    max: 100,
    step: 1,
  },
];
function simulate(p, start, end, lookback, cost) {
  let equity = 1,
    position = 0,
    peak = 1,
    drawdown = 0,
    trades = 0;
  const path = [];
  for (let t = start; t < end; t++) {
    // Position for return t uses only prices through t-1.
    const history = p.slice(t - lookback, t),
      ma = history.reduce((a, b) => a + b, 0) / lookback;
    const next = p[t - 1] > ma ? 1 : 0,
      turnover = Math.abs(next - position);
    trades += turnover;
    equity *= 1 + next * (p[t] / p[t - 1] - 1) - (turnover * cost) / 10000;
    position = next;
    peak = Math.max(peak, equity);
    drawdown = Math.min(drawdown, equity / peak - 1);
    path.push(equity);
  }
  if (position && path.length) {
    equity *= 1 - cost / 10000;
    trades++;
    path[path.length - 1] = equity;
    drawdown = Math.min(drawdown, equity / peak - 1);
  }
  return { equity, drawdown, trades, path };
}
export function backtest({ prices: p, train, test, costBps }) {
  if (
    !Number.isInteger(train) ||
    train < 30 ||
    !Number.isInteger(test) ||
    test < 1 ||
    costBps < 0 ||
    costBps > 1000 ||
    p.length <= train ||
    p.some((v) => !Number.isFinite(v) || v <= 0)
  )
    throw Error(
      "Use positive prices, train >= 30, test >= 1 and costs from 0 to 1000 bps.",
    );
  const folds = [];
  let equity = 1;
  const series = [1];
  for (let start = train; start < p.length; start += test) {
    const candidates = [5, 10, 20]
      .map((period) => ({
        period,
        ...simulate(p, start - train + 20, start, period, costBps),
      }))
      .sort((a, b) => b.equity - a.equity || a.period - b.period);
    const chosen = candidates[0],
      end = Math.min(p.length, start + test),
      result = simulate(p, start, end, chosen.period, costBps);
    series.push(...result.path.map((v) => v * equity));
    equity *= result.equity;
    folds.push({
      trainStart: start - train,
      trainEnd: start - 1,
      testStart: start,
      testEnd: end - 1,
      period: chosen.period,
      return: result.equity - 1,
      trades: result.trades,
    });
  }
  let peak = 1,
    dd = 0;
  for (const e of series) {
    peak = Math.max(peak, e);
    dd = Math.min(dd, e / peak - 1);
  }
  return { folds, series, equity, drawdown: dd };
}
export function run(i) {
  const r = backtest(i);
  return {
    summary: "Walk-forward results after trading costs",
    metrics: {
      "test return": (100 * (r.equity - 1)).toFixed(2) + "%",
      "max drawdown": (r.drawdown * 100).toFixed(2) + "%",
      "test windows": r.folds.length,
    },
    columns: [
      "train range",
      "unseen test range",
      "chosen lookback",
      "net return",
      "charged sides",
    ],
    rows: r.folds.map((f) => [
      `${f.trainStart}-${f.trainEnd}`,
      `${f.testStart}-${f.testEnd}`,
      f.period,
      (f.return * 100).toFixed(2) + "%",
      f.trades,
    ]),
    series: r.series,
    seriesLabel: "Out-of-sample equity, starting at 1",
    steps: [
      "Evaluate three lookbacks on the training window",
      "Freeze the chosen rule before the next test window",
      "Trade with lagged signals and cost on both sides",
      "Repeat; join only the unseen test returns",
    ],
    artifact: r,
  };
}
