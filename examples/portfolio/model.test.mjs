import test from "node:test";
import assert from "node:assert/strict";
import { backtest, metrics } from "./model.mjs";
import { readFileSync } from "node:fs";
const prices = JSON.parse(
    readFileSync(new URL("./data/spy.json", import.meta.url)),
).prices;
test("real prices generate finite out-of-sample results", () => {
    const r = backtest(prices);
    assert.ok(r.curve.length > 4000);
    assert.ok(Number.isFinite(r.stats.sharpe));
    assert.equal(r.curve[0].date, prices[504].date);
    assert.ok(r.windows.every((w) => w.trainTo < w.testFrom));
});
test("unseen future cannot change an earlier model choice or return", () => {
    const original = backtest(prices),
        altered = prices.map((r, i) =>
            i >= 1000 ? { ...r, close: r.close * 2 } : r,
        ),
        changed = backtest(altered);
    assert.deepEqual(
        original.windows.filter((w) => w.testFrom < prices[1000].date),
        changed.windows.filter((w) => w.testFrom < prices[1000].date),
    );
    assert.deepEqual(
        original.curve.filter((r) => r.date < prices[1000].date),
        changed.curve.filter((r) => r.date < prices[1000].date),
    );
});
test("costs reduce a fixed-rule strategy; flat data remain finite", () => {
    const a = backtest(prices, { periods: [60], costBps: 0 }),
        b = backtest(prices, { periods: [60], costBps: 50 });
    assert.ok(b.stats.total < a.stats.total);
    assert.equal(metrics([0, 0, 0]).sharpe, 0);
    assert.throws(() => backtest(prices, { costBps: -1 }));
});
