export function metrics(returns) {
    let equity = 1,
        peak = 1,
        dd = 0;
    for (const r of returns) {
        equity *= 1 + r;
        peak = Math.max(peak, equity);
        dd = Math.min(dd, equity / peak - 1);
    }
    const n = returns.length,
        mean = n ? returns.reduce((a, b) => a + b, 0) / n : 0,
        sd =
            n > 1
                ? Math.sqrt(
                      returns.reduce((s, r) => s + (r - mean) ** 2, 0) /
                          (n - 1),
                  )
                : 0;
    return {
        total: equity - 1,
        cagr: n ? equity ** (252 / n) - 1 : 0,
        sharpe: sd ? (mean / sd) * Math.sqrt(252) : 0,
        drawdown: dd,
    };
}
export function backtest(
    prices,
    {
        training = 504,
        testing = 63,
        costBps = 5,
        periods = [20, 60, 120, 200],
    } = {},
) {
    if (
        !Number.isInteger(training) ||
        training < Math.max(...periods) + 2 ||
        !Number.isInteger(testing) ||
        testing < 1 ||
        !Number.isFinite(costBps) ||
        costBps < 0 ||
        costBps > 1000
    )
        throw Error("Invalid window or cost");
    if (prices.length < training + testing)
        throw Error("Not enough historical prices for these windows");
    if (prices.some((p) => !Number.isFinite(p.close) || p.close <= 0))
        throw Error("Prices must be positive finite values");
    const closes = prices.map((p) => p.close),
        prefix = [0];
    for (const c of closes) prefix.push(prefix.at(-1) + c);
    const positions = Object.fromEntries(
        periods.map((n) => [
            n,
            closes.map((c, i) =>
                i >= n ? +(closes[i - 1] > (prefix[i] - prefix[i - n]) / n) : 0,
            ),
        ]),
    );
    const windows = [],
        curve = [],
        ret = [],
        bench = [];
    let eq = 1,
        buy = 1,
        lastPos = 0,
        trades = 0,
        fees = 0;
    for (let start = training; start < prices.length; start += testing) {
        const candidates = periods
            .map((period) => {
                const returns = [];
                let old = 0;
                for (let i = start - training + 1; i < start; i++) {
                    const pos = positions[period][i],
                        fee = (Math.abs(pos - old) * costBps) / 10000;
                    returns.push(pos * (closes[i] / closes[i - 1] - 1) - fee);
                    old = pos;
                }
                return { period, score: metrics(returns).sharpe };
            })
            .sort((a, b) => b.score - a.score || a.period - b.period);
        const period = candidates[0].period,
            end = Math.min(prices.length, start + testing);
        windows.push({
            trainFrom: prices[start - training].date,
            trainTo: prices[start - 1].date,
            testFrom: prices[start].date,
            testTo: prices[end - 1].date,
            period,
            trainingSharpe: candidates[0].score,
        });
        for (let i = start; i < end; i++) {
            const pos = positions[period][i],
                change = Math.abs(pos - lastPos),
                fee = (change * costBps) / 10000,
                daily = closes[i] / closes[i - 1] - 1,
                r = pos * daily - fee;
            eq *= 1 + r;
            buy *= 1 + daily;
            ret.push(r);
            bench.push(daily);
            fees += fee;
            trades += change;
            lastPos = pos;
            curve.push({
                date: prices[i].date,
                equity: eq,
                benchmark: buy,
                position: pos,
                period,
                return: r,
            });
        }
    }
    return {
        curve,
        windows,
        trades,
        costBps,
        fees,
        stats: metrics(ret),
        benchmark: metrics(bench),
    };
}
