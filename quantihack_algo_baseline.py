SYMBOLS = [
    "SYN-AAPL",
    "SYN-MSFT",
    "SYN-NVDA",
    "SYN-GOOG",
    "SYN-AMZN",
    "SYN-META",
    "SYN-TSLA",
    "FX-EURUSD",
    "FX-GBPUSD",
    "FX-USDJPY",
    "CMD-GOLD",
    "CMD-OIL",
    "CMD-BTC",
    "CMD-COPPER",
    "IDX-SP500",
    "IDX-FTSE",
]

MAX_ORDERS_PER_TICK = 50
MAX_POSITIONS = 6
MAX_NEW_ENTRIES_PER_TICK = 3
MAX_GROSS_NOTIONAL = 180000.0
MAX_PER_SYMBOL_NOTIONAL = 32000.0
MAX_SPREAD_RATIO = 0.0035

STOP_LOSS_PCT = 0.018
TAKE_PROFIT_PCT = 0.028
SCORE_ENTRY_THRESHOLD = 0.07
COOLDOWN_TICKS = 2


state = {
    "tick": 0,
    "cooldown": {},
}


def _returns(series):
    rets = []
    for idx in range(1, len(series)):
        prev = series[idx - 1]
        cur = series[idx]
        if prev > 0:
            rets.append((cur / prev) - 1.0)
    return rets


def _stdev(series):
    n_items = len(series)
    if n_items < 2:
        return 0.0
    mean = sum(series) / float(n_items)
    accum = 0.0
    for value in series:
        diff = value - mean
        accum += diff * diff
    return (accum / float(n_items)) ** 0.5


def _ema(series, period):
    n_items = len(series)
    if n_items < period or period <= 1:
        return None
    alpha = 2.0 / float(period + 1)
    ema_val = series[0]
    for value in series[1:]:
        ema_val = alpha * value + (1.0 - alpha) * ema_val
    return ema_val


def _rsi(series, period):
    if len(series) < period + 1:
        return None

    gains = 0.0
    losses = 0.0
    window = series[-(period + 1):]

    for idx in range(1, len(window)):
        delta = window[idx] - window[idx - 1]
        if delta > 0:
            gains += delta
        else:
            losses -= delta

    avg_gain = gains / float(period)
    avg_loss = losses / float(period)
    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _price_from_tick(symbol_tick):
    bid = symbol_tick.get("bid", 0.0)
    ask = symbol_tick.get("ask", 0.0)
    price = symbol_tick.get("price", 0.0)

    if bid > 0 and ask > 0:
        return 0.5 * (bid + ask)
    if price > 0:
        return price
    if ask > 0:
        return ask
    return bid


def _spread_ratio(symbol_tick):
    bid = symbol_tick.get("bid", 0.0)
    ask = symbol_tick.get("ask", 0.0)

    if bid <= 0 or ask <= 0:
        return 1.0

    mid = 0.5 * (bid + ask)
    if mid <= 0:
        return 1.0

    return (ask - bid) / mid


def _is_number(value):
    return isinstance(value, int) or isinstance(value, float)


def _to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _normalized_hist(hist):
    if not isinstance(hist, list) or len(hist) < 15:
        return []

    clean = []
    for value in hist[-40:]:
        if _is_number(value) and value > 0:
            clean.append(value)

    return clean


def _signal_score(hist, price):
    if price <= 0:
        return None

    hist = _normalized_hist(hist)
    if len(hist) < 15:
        return None

    ema_fast = _ema(hist, 5)
    ema_slow = _ema(hist, 12)
    rsi = _rsi(hist, 14)
    if not _is_number(ema_fast) or not _is_number(ema_slow) or not _is_number(rsi):
        return None
    ema_fast = _to_float(ema_fast)
    ema_slow = _to_float(ema_slow)
    rsi = _to_float(rsi)
    if ema_fast <= 0 or ema_slow <= 0:
        return None

    recent = hist[-15:]
    rets = _returns(recent)
    vol = _stdev(rets) if len(rets) > 2 else 0.0
    if not _is_number(vol):
        vol = 0.0
    vol = _to_float(vol)

    trend = (ema_fast / ema_slow) - 1.0
    distance = (price / ema_slow) - 1.0

    score = trend * 100.0 - max(0.0, abs(distance) - 0.015) * 5.0 - vol * 45.0

    if rsi > 72:
        score -= 0.25
    elif rsi < 35:
        score -= 0.10

    return score


def _open_order_side_map(orders):
    sides = {}
    for order in orders:
        sym = order.get("symbol")
        side = order.get("side")
        if not sym or not side:
            continue
        if sym not in sides:
            sides[sym] = set()
        sides[sym].add(side)
    return sides


def _pending_order_exposure(orders, prices, positions):
    pending_notional = 0.0
    pending_position_slots = 0

    for order in orders:
        sym = order.get("symbol")
        side = order.get("side")
        qty = order.get("qty", 0)

        if side != "BUY" or qty is None or qty <= 0 or not sym:
            continue

        tick_data = prices.get(sym, {})
        px = order.get("price", 0.0)
        if not _is_number(px) or px <= 0:
            px = _price_from_tick(tick_data)
        if px <= 0:
            continue

        pending_notional += qty * px

        held_qty = positions.get(sym, {}).get("qty", 0)
        if held_qty <= 0:
            pending_position_slots += 1

    return pending_notional, pending_position_slots


def on_tick(prices, positions, orders, history):
    state["tick"] += 1
    now_tick = state["tick"]

    result = []
    open_sides = _open_order_side_map(orders)

    gross_notional = 0.0
    positions_held = 0

    for sym, pos in positions.items():
        qty = pos.get("qty", 0)
        if qty < 0:
            if len(result) < MAX_ORDERS_PER_TICK and "BUY" not in open_sides.get(sym, set()):
                result.append({
                    "symbol": sym,
                    "side": "BUY",
                    "type": "MARKET",
                    "qty": int(abs(qty)),
                })
            continue
        if qty == 0:
            continue
        px = _price_from_tick(prices.get(sym, {}))
        if px <= 0:
            continue
        positions_held += 1
        gross_notional += qty * px

    for sym, pos in positions.items():
        qty = pos.get("qty", 0)
        if qty <= 0:
            continue
        if len(result) >= MAX_ORDERS_PER_TICK:
            return result

        if "SELL" in open_sides.get(sym, set()):
            continue

        tick_data = prices.get(sym, {})
        price = _price_from_tick(tick_data)
        if price <= 0:
            continue

        avg_entry = pos.get("avg_entry_price", 0.0)
        if avg_entry <= 0:
            avg_entry = price

        pnl = (price / avg_entry) - 1.0
        hist = _normalized_hist(history.get(sym, []))

        should_exit = False
        if pnl <= -STOP_LOSS_PCT or pnl >= TAKE_PROFIT_PCT:
            should_exit = True
        elif len(hist) >= 15:
            ema_slow = _ema(hist, 12)
            rsi = _rsi(hist, 14)
            if _is_number(ema_slow) and _is_number(rsi):
                ema_slow = _to_float(ema_slow)
                rsi = _to_float(rsi)
                if price < ema_slow * 0.994 or rsi >= 74:
                    should_exit = True

        if should_exit:
            result.append({
                "symbol": sym,
                "side": "SELL",
                "type": "MARKET",
                "qty": int(qty),
            })
            state["cooldown"][sym] = now_tick + COOLDOWN_TICKS

    pending_notional, pending_slots = _pending_order_exposure(orders, prices, positions)
    gross_notional += pending_notional
    positions_held += pending_slots

    if gross_notional >= MAX_GROSS_NOTIONAL or positions_held >= MAX_POSITIONS:
        return result

    candidates = []
    for sym in SYMBOLS:
        if sym not in prices:
            continue

        if len(result) >= MAX_ORDERS_PER_TICK:
            break

        pos_qty = positions.get(sym, {}).get("qty", 0)
        if pos_qty > 0:
            continue

        if "BUY" in open_sides.get(sym, set()):
            continue

        cool_until = state["cooldown"].get(sym, 0)
        if now_tick < cool_until:
            continue

        tick_data = prices.get(sym, {})
        if _spread_ratio(tick_data) > MAX_SPREAD_RATIO:
            continue

        price = _price_from_tick(tick_data)
        if price <= 0:
            continue

        hist = history.get(sym, [])
        score = _signal_score(hist, price)
        if score is None or score < SCORE_ENTRY_THRESHOLD:
            continue

        candidates.append((-score, sym, price))

    if not candidates:
        return result

    candidates.sort()

    slots_left = max(0, MAX_POSITIONS - positions_held)
    budget_left = max(0.0, MAX_GROSS_NOTIONAL - gross_notional)
    entries_left = min(MAX_NEW_ENTRIES_PER_TICK, slots_left)

    for neg_score, sym, price in candidates:
        if entries_left <= 0 or budget_left <= 0:
            break
        if len(result) >= MAX_ORDERS_PER_TICK:
            break

        target_notional = min(MAX_PER_SYMBOL_NOTIONAL, budget_left / float(entries_left))
        qty = int(target_notional / price)
        if qty <= 0:
            continue

        result.append({
            "symbol": sym,
            "side": "BUY",
            "type": "MARKET",
            "qty": qty,
        })

        entries_left -= 1
        budget_left -= qty * price

    return result
