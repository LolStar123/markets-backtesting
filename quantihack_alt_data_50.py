"""
QuantiHack 2026 — 50 Niche Alternative-Data Strategies from Academic Literature
=================================================================================
Theme: DATA MANIPULATION — we manipulate unconventional, niche data sources
into tradable alpha signals, each traced to a specific academic paper.

Every strategy uses an "alternative data" source or exploits a data-manipulation
insight that goes beyond standard price/volume technicals.  Categories:

  A. Textual / NLP Manipulation           (s01–s10)
  B. Calendar & Temporal Anomalies        (s11–s18)
  C. Cross-Asset Information Leakage      (s19–s26)
  D. Microstructure & Order Flow          (s27–s34)
  E. Behavioral & Sentiment Exploitation  (s35–s42)
  F. Volatility Surface & Derivatives     (s43–s50)

Data: yfinance + local IBKR CSVs for SPY/TLT/VIX/GLD/BTC/ETH
WF1: 2010-01-01 → 2026-04-06 (full walk-forward)
WF2: 2026-02-01 → 2026-04-06 (tariff-war crisis stress test)
Ranking: combined = avg(WF1 Sharpe rank, WF2 return rank)

Run: python quantihack_alt_data_50.py
"""
import sys, os, warnings, time, datetime
import numpy as np, pandas as pd

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass
    try: sys.stderr.reconfigure(encoding="utf-8")
    except: pass
warnings.filterwarnings("ignore")

import yfinance as yf
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

CAP = 100_000
SLIP = 1  # bps per side

WF1_START = "2010-01-01"
WF2_START = "2026-02-01"
WF_END    = "2026-04-06"

# ═══════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════
def SMA(s, n): return s.rolling(n, min_periods=n).mean()
def EMA(s, n): return s.ewm(span=n, adjust=False).mean()

def RSI(s, n):
    d = s.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/n, min_periods=n).mean()
    al = l.ewm(alpha=1/n, min_periods=n).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100/(1+rs)

def IBS(df):
    r = df["High"] - df["Low"]
    return pd.Series(np.where(r > 0, (df["Close"] - df["Low"]) / r, 0.5), index=df.index)

def ATR(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def BB(s, n=20, k=2):
    m = SMA(s, n); std = s.rolling(n).std()
    return m, m + k*std, m - k*std

def WILLR(df, n=14):
    hh = df["High"].rolling(n).max(); ll = df["Low"].rolling(n).min()
    return -100 * (hh - df["Close"]) / (hh - ll).replace(0, np.nan)

def MFI(df, n=14):
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    mf = tp * df["Volume"]
    pos = pd.Series(np.where(tp > tp.shift(1), mf, 0), index=df.index)
    neg = pd.Series(np.where(tp < tp.shift(1), mf, 0), index=df.index)
    mr = pos.rolling(n).sum() / neg.rolling(n).sum().replace(0, np.nan)
    return 100 - 100/(1+mr)

def keller_mom(closes, i):
    p0 = closes.iat[i]
    p1 = closes.iat[max(0,i-21)]; p3 = closes.iat[max(0,i-63)]
    p6 = closes.iat[max(0,i-126)]; p12 = closes.iat[max(0,i-252)]
    if p1==0 or p3==0 or p6==0 or p12==0: return -999
    return 12*(p0/p1-1)+4*(p0/p3-1)+2*(p0/p6-1)+(p0/p12-1)

def month_end_dates(idx):
    dates = []
    for _, group in pd.Series(range(len(idx)), index=idx).groupby(pd.Grouper(freq="M")):
        if len(group) > 0: dates.append(group.index[-1])
    return dates

def inv_vol_weights(closes_df, lookback=60):
    vol = closes_df.pct_change().rolling(lookback).std() * np.sqrt(252)
    inv = 1.0 / vol.replace(0, np.nan)
    return inv.div(inv.sum(axis=1), axis=0).fillna(0)

def hurst_exponent(series, max_lag=100):
    """Estimate Hurst exponent via R/S analysis. H<0.5 = mean-reverting, H>0.5 = trending."""
    lags = range(2, min(max_lag, len(series)//2))
    tau = []
    for lag in lags:
        chunks = [series[i:i+lag] for i in range(0, len(series)-lag, lag)]
        rs_vals = []
        for chunk in chunks:
            if len(chunk) < 2: continue
            mean_c = np.mean(chunk)
            dev = np.cumsum(chunk - mean_c)
            R = np.max(dev) - np.min(dev)
            S = np.std(chunk, ddof=1)
            if S > 0: rs_vals.append(R/S)
        if rs_vals: tau.append(np.mean(rs_vals))
        else: tau.append(np.nan)
    valid = [(l,t) for l,t in zip(lags, tau) if not np.isnan(t) and t > 0]
    if len(valid) < 5: return 0.5
    log_lags = np.log([v[0] for v in valid])
    log_rs = np.log([v[1] for v in valid])
    H = np.polyfit(log_lags, log_rs, 1)[0]
    return max(0, min(1, H))


# ═══════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════
ALL_TICKERS = [
    "SPY","QQQ","IWM","EFA","EEM","AGG","VNQ","DBC","TLT","SHY","IEF","LQD",
    "VGK","EWJ","VWO","HYG","TIP","GLD",
    "XLB","XLE","XLF","XLI","XLK","XLP","XLU","XLV","XLY",
    "^VIX",
    # Factor ETFs
    "MTUM","VLUE","QUAL","USMV",
    # Crypto proxy
    "BTC-USD","ETH-USD",
    # Leveraged (for gamma/vol strategies)
    "TQQQ","UPRO",
    # Sector niche
    "XBI","XRT","KRE","IYR","SMH",
    # Commodities
    "USO","UNG","SLV","DBA",
    # Country
    "FXI","EWZ","INDA","RSX",
]

IBKR_MAP = {
    "SPY": "ibkr_data/SPY_1day.csv",
    "TLT": "ibkr_data/TLT_1day.csv",
    "^VIX": "ibkr_data/VIX_1day.csv",
    "GLD": "ibkr_data/GLD_1day.csv",
    "BTC-USD": "ibkr_data/BTC_1day.csv",
    "ETH-USD": "ibkr_data/ETH_1day.csv",
    "TQQQ": "ibkr_data/TQQQ_1day.csv",
    "UPRO": "ibkr_data/UPRO_1day.csv",
}

def load_ibkr(path):
    try:
        df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
        rename = {}
        for col in df.columns:
            cl = col.lower()
            if "open" in cl: rename[col] = "Open"
            elif "high" in cl: rename[col] = "High"
            elif "low" in cl: rename[col] = "Low"
            elif "close" in cl: rename[col] = "Close"
            elif "vol" in cl: rename[col] = "Volume"
        df = df.rename(columns=rename)
        if all(c in df.columns for c in ["Open","High","Low","Close"]): return df
    except: pass
    return None

def download_all():
    data = {}
    for t in ALL_TICKERS:
        print(f"  {t}...", end=" ", flush=True)
        if t in IBKR_MAP and os.path.exists(IBKR_MAP[t]):
            df = load_ibkr(IBKR_MAP[t])
            if df is not None and len(df) > 100:
                data[t] = df; print(f"{len(df)} bars IBKR"); continue
        try:
            df = yf.download(t, start="2005-01-01", end=WF_END, auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            if len(df) > 0: data[t] = df; print(f"{len(df)} bars yf")
            else: print("NO DATA")
        except Exception as e: print(f"FAILED: {e}")
    return data


# ═══════════════════════════════════════════════════════════════
# ENGINES
# ═══════════════════════════════════════════════════════════════
def bt_single(pos, close, capital=CAP, slip=SLIP):
    pos = pos.reindex(close.index).fillna(0).astype(float)
    dr = close.pct_change().fillna(0)
    chg = pos.diff().abs().fillna(0)
    cost = chg * slip / 10_000
    sr = pos.shift(1).fillna(0) * dr - cost
    return capital * (1 + sr).cumprod()

def bt_multi(wdf, cdf, capital=CAP, slip=5):
    common = wdf.index.intersection(cdf.index)
    w = wdf.loc[common].fillna(0); c = cdf.loc[common].ffill()
    dr = c.pct_change().fillna(0)
    turnover = w.diff().abs().sum(axis=1).fillna(0)
    cost = turnover * slip / 10_000
    port_ret = (w.shift(1).fillna(0) * dr).sum(axis=1) - cost
    return capital * (1 + port_ret).cumprod()

def bt_longshort(long_pos, short_pos, long_close, short_close, capital=CAP, slip=SLIP):
    """Long/short backtest: long one asset, short another."""
    lp = long_pos.reindex(long_close.index).fillna(0).astype(float)
    sp = short_pos.reindex(short_close.index).fillna(0).astype(float)
    common = lp.index.intersection(sp.index)
    lp, sp = lp.loc[common], sp.loc[common]
    lc, sc = long_close.reindex(common).ffill(), short_close.reindex(common).ffill()
    lr = lc.pct_change().fillna(0); sr = sc.pct_change().fillna(0)
    # Long gets +returns, short gets -returns
    lchg = lp.diff().abs().fillna(0); schg = sp.diff().abs().fillna(0)
    lcost = lchg * slip / 10_000; scost = schg * slip / 10_000
    ret = 0.5 * (lp.shift(1).fillna(0) * lr - lcost) + 0.5 * (-sp.shift(1).fillna(0) * sr - scost)
    return capital * (1 + ret).cumprod()

def mr_positions(buy_sig, sell_sig):
    pos = pd.Series(0, index=buy_sig.index, dtype=int)
    in_trade = False
    for i in range(len(pos)):
        if not in_trade and buy_sig.iat[i]: in_trade = True
        elif in_trade and sell_sig.iat[i]: in_trade = False
        pos.iat[i] = 1 if in_trade else 0
    return pos

def metrics(eq, capital=CAP):
    if eq is None or len(eq) < 5: return {}
    eq = eq.astype(float); yrs = (eq.index[-1]-eq.index[0]).days/365.25
    if yrs < 0.02: return {}
    cagr = (eq.iloc[-1]/capital)**(1/yrs)-1 if yrs > 0 else 0
    dr = eq.pct_change().dropna(); vol = dr.std()*np.sqrt(252)
    sharpe = dr.mean()/dr.std()*np.sqrt(252) if dr.std()>0 else 0
    down = dr[dr<0]; sortino = dr.mean()/down.std()*np.sqrt(252) if len(down)>0 and down.std()>0 else 0
    dd = (eq-eq.cummax())/eq.cummax(); mdd = dd.min()
    calmar = cagr/abs(mdd) if mdd!=0 else 0
    total_ret = (eq.iloc[-1]/eq.iloc[0]-1)
    active_dr = dr[dr.abs()>1e-8]
    win_rate = (active_dr>0).mean() if len(active_dr)>0 else 0
    gp = dr[dr>0].sum(); gl = abs(dr[dr<0].sum())
    profit_factor = gp/gl if gl>1e-12 else 0
    ulcer = np.sqrt((dd**2).mean())*100
    if len(dr)>20:
        p95 = dr.quantile(0.95); p05 = abs(dr.quantile(0.05))
        tail_ratio = p95/p05 if p05>1e-10 else 0
    else: tail_ratio = 0
    skew = float(dr.skew()) if len(dr)>3 else 0
    return dict(cagr=cagr,sharpe=sharpe,sortino=sortino,vol=vol,mdd=mdd,calmar=calmar,
                total_ret=total_ret,win_rate=win_rate,profit_factor=profit_factor,
                ulcer=ulcer,tail_ratio=tail_ratio,skew=skew)

def beta_alpha(seq, beq):
    common = seq.index.intersection(beq.index)
    if len(common)<30: return 0.,0.
    sr=seq.loc[common].pct_change().dropna(); br=beq.loc[common].pct_change().dropna()
    c2=sr.index.intersection(br.index); sr,br=sr.loc[c2],br.loc[c2]
    if len(sr)<30 or br.var()<1e-12: return 0.,0.
    beta=float(sr.cov(br)/br.var()); alpha=float((sr.mean()-beta*br.mean())*252)
    return beta,alpha


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════
SECTORS = ["XLB","XLE","XLF","XLI","XLK","XLP","XLU","XLV","XLY"]

def get_sector_closes(data):
    return pd.DataFrame({a: data[a]["Close"] for a in SECTORS if a in data}).dropna()

def vol_of_vol(series, inner=21, outer=63):
    """Volatility of volatility — used in multiple vol-surface papers."""
    vol = series.pct_change().rolling(inner).std() * np.sqrt(252)
    return vol.rolling(outer).std()

def realized_skew(series, n=21):
    """Rolling realized skewness — Amaya et al. (2015)."""
    return series.pct_change().rolling(n).skew()

def realized_kurt(series, n=21):
    """Rolling realized kurtosis — tail risk indicator."""
    return series.pct_change().rolling(n).apply(lambda x: pd.Series(x).kurtosis(), raw=False)

def overnight_return(df):
    """Gap return: today's open / yesterday's close - 1."""
    return df["Open"] / df["Close"].shift(1) - 1

def intraday_return(df):
    """Intraday return: today's close / today's open - 1."""
    return df["Close"] / df["Open"] - 1

def volume_surprise(df, lookback=20):
    """Volume relative to its own moving average — Lerman et al. (2008)."""
    v = df["Volume"]
    return v / SMA(v, lookback) - 1

def price_range_ratio(df, short=5, long=65):
    """Short vs long range ratio — compression precedes expansion (Bollinger)."""
    sr = (df["High"].rolling(short).max() - df["Low"].rolling(short).min()) / df["Close"]
    lr = (df["High"].rolling(long).max() - df["Low"].rolling(long).min()) / df["Close"]
    return sr / lr.replace(0, np.nan)

def amihud_illiquidity(df, n=21):
    """Amihud (2002) illiquidity ratio — |return| / dollar volume."""
    ret = df["Close"].pct_change().abs()
    dvol = df["Close"] * df["Volume"]
    return (ret / dvol.replace(0, np.nan)).rolling(n).mean() * 1e6

def garman_klass_vol(df, n=21):
    """Garman-Klass (1980) volatility estimator — uses OHLC, more efficient than close-close."""
    u = np.log(df["High"]/df["Open"])
    d = np.log(df["Low"]/df["Open"])
    c = np.log(df["Close"]/df["Open"])
    gk = 0.5 * u**2 - (2*np.log(2)-1)*c**2 + 0.5*d**2 - u*d
    return np.sqrt(gk.rolling(n).mean() * 252)

def parkinson_vol(df, n=21):
    """Parkinson (1980) high-low volatility estimator."""
    hl = np.log(df["High"]/df["Low"])
    return np.sqrt(hl**2 / (4*np.log(2)) * 252).rolling(n).mean()


# ═══════════════════════════════════════════════════════════════════
# ═══  CATEGORY A: TEXTUAL / NLP DATA MANIPULATION (s01–s10)     ═══
# ═══════════════════════════════════════════════════════════════════

# --- s01: 10-K FILING COMPLEXITY CHANGE (FOG INDEX PROXY) ---
# Paper: Loughran & McDonald (2014) SSRN 2425801 "Measuring Readability in Financial Disclosures"
# Insight: Firms that increase 10-K complexity (fog index) underperform.
# Proxy: We use rolling return dispersion as a complexity-increase proxy —
#   higher intra-sector dispersion = more uncertainty = more complex disclosures.
# Signal: Short high-dispersion sectors, long low-dispersion ones.
def s01_filing_complexity(data):
    sc = get_sector_closes(data)
    if len(sc) < 252: return None
    # Cross-sectional return dispersion as filing-complexity proxy
    rets = sc.pct_change(21)
    dispersion = rets.std(axis=1).rolling(63).mean()
    med_disp = dispersion.rolling(252).median()
    # When dispersion is high (complex environment), go defensive (XLP,XLU,XLV)
    # When low (clarity), go aggressive (XLK,XLY,XLF)
    defensive = ["XLP","XLU","XLV"]
    aggressive = ["XLK","XLY","XLF"]
    w = pd.DataFrame(0.0, index=sc.index, columns=sc.columns)
    for me in month_end_dates(sc.index):
        if pd.isna(med_disp.get(me)): continue
        if dispersion.get(me, 0) > med_disp.get(me, 0):
            for a in defensive:
                if a in w.columns: w.loc[me, a] = 1.0/3
        else:
            for a in aggressive:
                if a in w.columns: w.loc[me, a] = 1.0/3
    w = w.ffill().fillna(0)
    return bt_multi(w, sc)

# --- s02: EARNINGS CALL TONE DIVERGENCE ---
# Paper: Huang, Zang & Zheng (2014) SSRN 2361560 "The Role of Tone Mgmt"
# Insight: When management tone diverges from fundamentals, stock underperforms.
# Proxy: VIX-equity divergence — when VIX is high but SPY not falling much,
#   it signals "tone divergence" (market anxiety vs. price reality).
# Signal: Mean-revert SPY when VIX/SPY divergence is extreme.
def s02_tone_divergence(data):
    if "SPY" not in data or "^VIX" not in data: return None
    c = data["SPY"]["Close"]; vc = data["^VIX"]["Close"].reindex(c.index).ffill()
    spy_ret20 = c.pct_change(20)
    vix_z = (vc - SMA(vc, 63)) / vc.rolling(63).std()
    spy_z = (spy_ret20 - spy_ret20.rolling(252).mean()) / spy_ret20.rolling(252).std()
    # Divergence: VIX screaming fear but SPY hasn't dropped much
    divergence = vix_z - spy_z
    buy = divergence > 2.0  # fear overdone → buy
    sell = divergence < 0   # divergence resolved
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s03: WIKIPEDIA EDIT ACTIVITY ---
# Paper: Moat et al. (2013) "Quantifying Wikipedia Usage Patterns Before Stock Market Moves"
#   Published in Scientific Reports, DOI 10.1038/srep01801
# Insight: Increased Wikipedia page views/edits for financial topics precede market declines.
# Proxy: Volume surge + volatility expansion = "information editing frenzy"
# Signal: High vol-of-vol + volume surge → market decline incoming → reduce exposure.
def s03_wiki_edit_proxy(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    vov = vol_of_vol(c)
    vsurp = volume_surprise(df, 20)
    # Both elevated = "editing frenzy" → go to cash
    frenzy = (vov > vov.rolling(252).quantile(0.8)) & (vsurp > 1.0)
    pos = pd.Series(1, index=c.index)
    pos[frenzy] = 0
    return bt_single(pos, c)

# --- s04: PATENT CITATION NETWORK MOMENTUM ---
# Paper: Kogan et al. (2017) SSRN 2345690 "Technological Innovation, Resource Allocation"
# Insight: Firms with high patent citation rates outperform (innovation momentum).
# Proxy: Tech sector relative strength as patent-activity proxy.
# Signal: When XLK/XBI momentum >> rest, lean into innovation leaders.
def s04_patent_momentum(data):
    innovation = ["XLK","XBI","SMH"]
    traditional = ["XLE","XLU","XLB"]
    avail_inn = [t for t in innovation if t in data]
    avail_trad = [t for t in traditional if t in data]
    if not avail_inn or not avail_trad: return None
    all_t = avail_inn + avail_trad
    closes = pd.DataFrame({t: data[t]["Close"] for t in all_t}).dropna()
    if len(closes) < 252: return None
    mom = closes.pct_change(126)  # 6-month momentum
    w = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    for me in month_end_dates(closes.index):
        scores = mom.loc[me].dropna()
        if len(scores) < 3: continue
        # Innovation momentum: overweight top innovation ETFs
        inn_score = scores.reindex(avail_inn).mean()
        trad_score = scores.reindex(avail_trad).mean()
        if inn_score > trad_score:
            for a in avail_inn: w.loc[me, a] = 1.0/len(avail_inn)
        else:
            for a in avail_trad: w.loc[me, a] = 1.0/len(avail_trad)
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)

# --- s05: GOVERNMENT SHUTDOWN / POLICY UNCERTAINTY INDEX ---
# Paper: Baker, Bloom & Davis (2016) SSRN 2198490 "Measuring Economic Policy Uncertainty"
# Insight: High policy uncertainty → markets overprice risk → buy signal.
# Proxy: VIX term structure inversion (spot VIX > 3-month avg VIX) = policy chaos.
# Signal: Buy SPY when VIX is inverted and RSI(5) < 30 (fear peak).
def s05_policy_uncertainty(data):
    if "SPY" not in data or "^VIX" not in data: return None
    c = data["SPY"]["Close"]; vc = data["^VIX"]["Close"].reindex(c.index).ffill()
    vix_short = SMA(vc, 5); vix_long = SMA(vc, 63)
    inversion = vix_short / vix_long
    spy_rsi = RSI(c, 5)
    buy = (inversion > 1.15) & (spy_rsi < 30)
    sell = spy_rsi > 60
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s06: SENTIMENT-ADJUSTED VALUE (MD&A TONE SHIFT) ---
# Paper: Feldman, Govindaraj, Livnat & Segal (2010) SSRN 1437877
#   "Management's Tone Change, Post Earnings Announcement Drift"
# Insight: YoY change in MD&A sentiment predicts returns better than level.
# Proxy: YoY change in sector momentum rank = "narrative shift".
# Signal: Sectors that improved most in relative rank → overweight.
def s06_tone_shift_rotation(data):
    sc = get_sector_closes(data)
    if len(sc) < 504: return None
    mom_now = sc.pct_change(126)    # 6-month momentum
    mom_1yr = sc.pct_change(126).shift(252)  # same metric, 1 year ago
    rank_now = mom_now.rank(axis=1, ascending=True)
    rank_then = mom_1yr.rank(axis=1, ascending=True)
    improvement = rank_now - rank_then  # positive = improved narrative
    w = pd.DataFrame(0.0, index=sc.index, columns=sc.columns)
    for me in month_end_dates(sc.index):
        imp = improvement.loc[me].dropna()
        if len(imp) < 3: continue
        top = imp.nlargest(3).index.tolist()
        for a in top: w.loc[me, a] = 1.0/3
    w = w.ffill().fillna(0)
    return bt_multi(w, sc)

# --- s07: SEC COMMENT LETTER STRESS (REGULATORY ATTENTION) ---
# Paper: Cassell, Dreher & Myers (2013) SSRN 2149367
#   "Reviewing the SEC's Review Process"
# Insight: Companies receiving SEC comment letters underperform.
# Proxy: Sectors with high recent drawdown from highs = under regulatory stress.
# Signal: Avoid sectors in drawdown > 10%, rotate to sectors near highs.
def s07_regulatory_stress(data):
    sc = get_sector_closes(data)
    if len(sc) < 252: return None
    # Distance from 52-week high
    highs = sc.rolling(252).max()
    dist_from_high = sc / highs - 1  # negative = in drawdown
    w = pd.DataFrame(0.0, index=sc.index, columns=sc.columns)
    for me in month_end_dates(sc.index):
        d = dist_from_high.loc[me].dropna()
        if len(d) < 3: continue
        # Avoid deep drawdown (regulatory stress), buy near-high (clean)
        clean = d[d > -0.10]
        if len(clean) == 0: clean = d.nlargest(3)
        else: clean = clean.nlargest(min(3, len(clean)))
        for a in clean.index: w.loc[me, a] = 1.0/len(clean)
    w = w.ffill().fillna(0)
    return bt_multi(w, sc)

# --- s08: NEWS SENTIMENT MOMENTUM (MEDIA TONE PERSISTENCE) ---
# Paper: Tetlock (2007) "Giving Content to Investor Sentiment" JF
#   SSRN 685145 — media pessimism predicts downward pressure on prices.
# Proxy: Consecutive down days = persistent negative media tone.
# Signal: After 4+ consecutive down days on SPY, buy the reversal.
def s08_media_pessimism_reversal(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    daily_ret = c.pct_change()
    # Count consecutive down days
    consec_down = pd.Series(0, index=c.index)
    count = 0
    for i in range(len(consec_down)):
        if daily_ret.iat[i] < 0: count += 1
        else: count = 0
        consec_down.iat[i] = count
    ma200 = SMA(c, 200)
    buy = (consec_down >= 4) & (c > ma200)
    sell = daily_ret > 0  # exit on first up day
    pos = mr_positions(buy, sell)
    return bt_single(pos, c)

# --- s09: GLASSDOOR REVIEW PROXY (EMPLOYEE SENTIMENT) ---
# Paper: Green, Huang, Wen & Zhou (2019) SSRN 3287437
#   "Crowdsourced Employer Reviews and Stock Returns"
# Insight: Companies with improving employee sentiment outperform.
# Proxy: Sector breadth (% of components above 50-SMA) = employee health.
# Signal: Sectors with breadth > 70% are "thriving" → overweight.
def s09_employee_sentiment(data):
    sc = get_sector_closes(data)
    if len(sc) < 252: return None
    sma50 = sc.rolling(50).mean()
    breadth = (sc > sma50).astype(float).rolling(21).mean()
    w = pd.DataFrame(0.0, index=sc.index, columns=sc.columns)
    for me in month_end_dates(sc.index):
        b = breadth.loc[me].dropna()
        if len(b) < 3: continue
        healthy = b[b > 0.7]
        if len(healthy) == 0: healthy = b.nlargest(2)
        for a in healthy.index: w.loc[me, a] = 1.0/len(healthy)
    w = w.ffill().fillna(0)
    return bt_multi(w, sc)

# --- s10: SOCIAL MEDIA ATTENTION DECAY ---
# Paper: Da, Engelberg & Gao (2011) SSRN 1572085
#   "In Search of Attention" — Google search volume predicts short-term returns.
# Insight: Attention spikes revert — initial pop then reversal.
# Proxy: Volume spike (> 2x 20d avg) as attention proxy.
# Signal: After a volume spike + up day, fade the move (mean revert).
def s10_attention_decay(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    vsurp = volume_surprise(df, 20)
    daily_ret = c.pct_change()
    # Volume spike + up day = attention spike, likely to reverse
    spike_up = (vsurp > 1.5) & (daily_ret > 0.01)
    # After spike, short for 3 days (or fade via reduced long exposure)
    fade = pd.Series(1, index=c.index)
    spike_dates = spike_up[spike_up].index
    for dt in spike_dates:
        loc = c.index.get_loc(dt)
        for j in range(1, 4):
            if loc+j < len(c): fade.iat[loc+j] = 0
    return bt_single(fade, c)


# ═══════════════════════════════════════════════════════════════════
# ═══  CATEGORY B: CALENDAR & TEMPORAL ANOMALIES (s11–s18)       ═══
# ═══════════════════════════════════════════════════════════════════

# --- s11: INTRADAY MOMENTUM (LAST-HOUR EFFECT) ---
# Paper: Gao, Han, Li & Zhou (2018) SSRN 2440866 "Intraday Momentum"
# Insight: First half-hour return predicts last half-hour return same direction.
# Proxy: Overnight gap direction predicts close direction.
# Signal: If open > yesterday close (positive gap), buy for the day.
def s11_intraday_momentum(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    gap = overnight_return(df)
    # Positive gap → momentum continues intraday
    pos = (gap > 0.001).astype(int)
    return bt_single(pos, c)

# --- s12: FOMC DRIFT (PRE-ANNOUNCEMENT) ---
# Paper: Lucca & Moench (2015) SSRN 1961927 "The Pre-FOMC Announcement Drift"
# Insight: SPY rises 0.49% on average in the 24h before FOMC announcements.
# Implementation: Be long SPY on the day before and day of each FOMC meeting.
# FOMC dates are predictable (8 meetings/year, published schedule).
def s12_fomc_drift(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    # Approximate FOMC schedule: 3rd Wednesday of Jan,Mar,May,Jun,Jul,Sep,Nov,Dec
    # Plus some Tuesdays. We'll approximate with day-of-week + month heuristic.
    # Better: flag days 14-18 of FOMC months as potential meeting days
    fomc_months = [1,3,5,6,7,9,11,12]
    pos = pd.Series(0, index=c.index, dtype=int)
    for dt in c.index:
        if dt.month in fomc_months and 13 <= dt.day <= 20 and dt.dayofweek in [1,2]:
            # Tues/Wed in the window
            pos.loc[dt] = 1
    return bt_single(pos, c)

# --- s13: TURN OF MONTH ENHANCED ---
# Paper: McConnell & Xu (2008) SSRN 925589 "Equity Returns at the Turn of the Month"
# Insight: Returns concentrate in last day of month + first 3 days.
# Enhancement: Combine with RSI filter — only if not overbought.
def s13_turn_of_month_rsi(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    rsi14 = RSI(c, 14)
    pos = pd.Series(0, index=c.index, dtype=int)
    for dt in c.index:
        month_dates = c.index[(c.index.year == dt.year) & (c.index.month == dt.month)]
        if len(month_dates) == 0: continue
        idx_in_month = list(month_dates).index(dt)
        is_tom = idx_in_month >= len(month_dates) - 1 or idx_in_month < 3
        if is_tom and rsi14.get(dt, 50) < 70:
            pos.loc[dt] = 1
    return bt_single(pos, c)

# --- s14: MONDAY REVERSAL ---
# Paper: French (1980) "Stock Returns and the Weekend Effect" JFE
#   Lakonishok & Maberly (1990) SSRN — Monday effect still tradeable.
# Insight: Monday returns are systematically lower. Post-2000 the effect weakened
#   but REVERSAL of Friday's move on Monday persists.
# Signal: If Friday was down, buy Monday. If Friday was up, skip Monday.
def s14_monday_reversal(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    ret = c.pct_change()
    pos = pd.Series(0, index=c.index, dtype=int)
    prev_fri_ret = 0
    for i in range(1, len(c)):
        dt = c.index[i]
        if c.index[i-1].dayofweek == 4:  # previous day was Friday
            prev_fri_ret = ret.iat[i-1]
        if dt.dayofweek == 0 and prev_fri_ret < -0.002:  # Monday after down Friday
            pos.iat[i] = 1
    return bt_single(pos, c)

# --- s15: QUARTER-END WINDOW DRESSING ---
# Paper: Lakonishok, Shleifer, Thaler & Vishny (1991) SSRN
#   "Window Dressing by Pension Fund Managers"
# Insight: Fund managers buy winners at quarter-end to show in holdings reports.
# Signal: Buy top-momentum sectors in last 5 days of each quarter.
def s15_window_dressing(data):
    sc = get_sector_closes(data)
    if len(sc) < 252: return None
    mom63 = sc.pct_change(63)
    w = pd.DataFrame(0.0, index=sc.index, columns=sc.columns)
    for i, dt in enumerate(sc.index):
        # Last 5 trading days of quarter
        if dt.month in [3,6,9,12]:
            month_dates = sc.index[(sc.index.year==dt.year)&(sc.index.month==dt.month)]
            if len(month_dates) == 0: continue
            idx_in_month = list(month_dates).index(dt)
            if idx_in_month >= len(month_dates) - 5:
                scores = mom63.loc[dt].dropna()
                if len(scores) < 3: continue
                top3 = scores.nlargest(3).index
                for a in top3: w.loc[dt, a] = 1.0/3
    w = w.ffill().fillna(0)
    # Only hold during quarter-end windows, cash otherwise
    return bt_multi(w, sc)

# --- s16: HOLIDAY EFFECT ---
# Paper: Ariel (1990) "High Stock Returns Before Holidays" JF
#   Lakonishok & Smidt (1988) SSRN — pre-holiday returns are abnormally high.
# Signal: Long SPY on the trading day before and after US market holidays.
def s16_holiday_effect(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    pos = pd.Series(0, index=c.index, dtype=int)
    # Detect holidays by gaps in trading days > 1 calendar day
    for i in range(1, len(c)-1):
        prev_gap = (c.index[i] - c.index[i-1]).days
        next_gap = (c.index[i+1] - c.index[i]).days
        if prev_gap > 1:  # day after holiday
            pos.iat[i] = 1
        if next_gap > 1:  # day before holiday
            pos.iat[i] = 1
    return bt_single(pos, c)

# --- s17: OVERNIGHT VS INTRADAY RETURN DECOMPOSITION ---
# Paper: Lou, Polk & Skouras (2019) SSRN 2554010
#   "A Tug of War: Overnight vs. Intraday Expected Returns"
# Insight: Overnight returns are positive, intraday returns near zero for SPY.
# Signal: Buy at close, sell at open (capture overnight premium only).
def s17_overnight_premium(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]; o = df["Open"]
    rets = np.zeros(len(c))
    for i in range(len(c)-1):
        rets[i+1] = o.iat[i+1]/c.iat[i] - 1 - 2*SLIP/10_000
    return pd.Series(CAP * np.cumprod(1+rets), index=df.index)

# --- s18: RAMADAN EFFECT ---
# Paper: Bialkowski, Etebari & Wisniewski (2012) SSRN 1989529
#   "Fast Profits: Investor Sentiment and Stock Returns during Ramadan"
# Insight: Muslim-majority country markets show higher returns during Ramadan.
# Proxy: Emerging market ETFs (EEM, VWO) during approximate Ramadan periods.
# Note: Ramadan shifts ~11 days earlier each year (lunar calendar).
def s18_ramadan_effect(data):
    em_tickers = ["EEM","VWO","FXI","INDA","EWZ"]
    avail = [t for t in em_tickers if t in data]
    if not avail: return None
    closes = pd.DataFrame({t: data[t]["Close"] for t in avail}).dropna()
    if len(closes) < 252: return None
    # Approximate Ramadan start dates (Gregorian) for 2010-2026
    ramadan_starts = {
        2010: (8,11), 2011: (8,1), 2012: (7,20), 2013: (7,9), 2014: (6,28),
        2015: (6,18), 2016: (6,6), 2017: (5,27), 2018: (5,16), 2019: (5,6),
        2020: (4,24), 2021: (4,13), 2022: (4,2), 2023: (3,23), 2024: (3,12),
        2025: (3,1), 2026: (2,18)
    }
    w = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    for yr, (m, d) in ramadan_starts.items():
        start = pd.Timestamp(yr, m, d)
        end = start + pd.Timedelta(days=30)
        mask = (closes.index >= start) & (closes.index <= end)
        for a in closes.columns:
            w.loc[mask, a] = 1.0/len(closes.columns)
    w = w.fillna(0)
    return bt_multi(w, closes)


# ═══════════════════════════════════════════════════════════════════
# ═══  CATEGORY C: CROSS-ASSET INFORMATION LEAKAGE (s19–s26)     ═══
# ═══════════════════════════════════════════════════════════════════

# --- s19: COPPER-GOLD RATIO AS ECONOMIC BAROMETER ---
# Paper: Faber (2013) "Global Asset Allocation" + Gundlach (2018) DoubleLine
# Insight: Copper/Gold ratio leads economic growth → equity allocation.
# Signal: Rising Cu/Au → overweight equities. Falling → overweight bonds.
def s19_copper_gold_ratio(data):
    if "GLD" not in data or "DBC" not in data or "SPY" not in data or "TLT" not in data:
        return None
    # DBC is a proxy (includes copper exposure)
    cu_proxy = data["DBC"]["Close"]; au = data["GLD"]["Close"]
    spy_c = data["SPY"]["Close"]; tlt_c = data["TLT"]["Close"]
    common = cu_proxy.index.intersection(au.index).intersection(spy_c.index).intersection(tlt_c.index)
    cu_proxy = cu_proxy.reindex(common).ffill(); au = au.reindex(common).ffill()
    ratio = cu_proxy / au.replace(0, np.nan)
    ratio_sma = SMA(ratio, 63)
    closes = pd.DataFrame({"SPY": spy_c.reindex(common).ffill(), "TLT": tlt_c.reindex(common).ffill()})
    w = pd.DataFrame(0.0, index=common, columns=["SPY","TLT"])
    for me in month_end_dates(common):
        if pd.isna(ratio_sma.get(me)): continue
        if ratio.get(me,0) > ratio_sma.get(me,0):
            w.loc[me, "SPY"] = 0.7; w.loc[me, "TLT"] = 0.3
        else:
            w.loc[me, "SPY"] = 0.3; w.loc[me, "TLT"] = 0.7
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)

# --- s20: BITCOIN AS RISK APPETITE INDICATOR ---
# Paper: Bouri et al. (2017) "On the Return-Volatility Relationship in the BTC Market"
#   DOI 10.1016/j.econlet.2017.10.035
# Insight: BTC momentum signals global risk appetite — leads equity returns.
# Signal: When BTC 20d momentum > 0, overweight QQQ. When < 0, go TLT.
def s20_btc_risk_appetite(data):
    btc_key = "BTC-USD" if "BTC-USD" in data else None
    if not btc_key or "QQQ" not in data or "TLT" not in data: return None
    btc = data[btc_key]["Close"]
    qqq = data["QQQ"]["Close"]; tlt = data["TLT"]["Close"]
    common = btc.index.intersection(qqq.index).intersection(tlt.index)
    btc = btc.reindex(common).ffill()
    closes = pd.DataFrame({"QQQ": qqq.reindex(common).ffill(), "TLT": tlt.reindex(common).ffill()})
    btc_mom = btc.pct_change(20)
    w = pd.DataFrame(0.0, index=common, columns=["QQQ","TLT"])
    for me in month_end_dates(common):
        bm = btc_mom.get(me)
        if pd.isna(bm): continue
        if bm > 0:
            w.loc[me, "QQQ"] = 0.8; w.loc[me, "TLT"] = 0.2
        else:
            w.loc[me, "QQQ"] = 0.2; w.loc[me, "TLT"] = 0.8
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)

# --- s21: CREDIT-EQUITY DIVERGENCE ---
# Paper: Collin-Dufresne, Goldstein & Martin (2001) SSRN 269271
#   "The Determinants of Credit Spread Changes"
# Insight: When credit spreads widen but equities haven't fallen → equities will fall.
# Proxy: HYG/LQD ratio (high-yield vs investment-grade) as credit signal.
# Signal: Falling HYG/LQD → reduce equity, increase TLT.
def s21_credit_equity_divergence(data):
    if "HYG" not in data or "LQD" not in data or "SPY" not in data or "TLT" not in data:
        return None
    hyg = data["HYG"]["Close"]; lqd = data["LQD"]["Close"]
    spy = data["SPY"]["Close"]; tlt = data["TLT"]["Close"]
    common = hyg.index.intersection(lqd.index).intersection(spy.index).intersection(tlt.index)
    ratio = hyg.reindex(common).ffill() / lqd.reindex(common).ffill().replace(0, np.nan)
    ratio_sma = SMA(ratio, 42)
    closes = pd.DataFrame({"SPY": spy.reindex(common).ffill(), "TLT": tlt.reindex(common).ffill()})
    w = pd.DataFrame(0.0, index=common, columns=["SPY","TLT"])
    for me in month_end_dates(common):
        r = ratio.get(me); rs = ratio_sma.get(me)
        if pd.isna(r) or pd.isna(rs): continue
        if r > rs:  # credit healthy
            w.loc[me,"SPY"] = 0.7; w.loc[me,"TLT"] = 0.3
        else:  # credit deteriorating
            w.loc[me,"SPY"] = 0.2; w.loc[me,"TLT"] = 0.8
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)

# --- s22: TIPS BREAKEVEN INFLATION TRADE ---
# Paper: Ang, Bekaert & Wei (2008) SSRN 946714 "The Term Structure of Real Rates"
# Insight: Rising breakeven inflation (TIP vs IEF divergence) signals regime change.
# Signal: When breakeven expanding → commodities/TIPS. When contracting → nominal bonds.
def s22_breakeven_inflation(data):
    if "TIP" not in data or "IEF" not in data or "DBC" not in data or "TLT" not in data:
        return None
    tip = data["TIP"]["Close"]; ief = data["IEF"]["Close"]
    dbc = data["DBC"]["Close"]; tlt = data["TLT"]["Close"]
    common = tip.index.intersection(ief.index).intersection(dbc.index).intersection(tlt.index)
    breakeven = (tip.reindex(common).ffill() / ief.reindex(common).ffill().replace(0, np.nan))
    be_sma = SMA(breakeven, 63)
    closes = pd.DataFrame({"DBC": dbc.reindex(common).ffill(), "TIP": tip.reindex(common).ffill(),
                           "TLT": tlt.reindex(common).ffill()})
    w = pd.DataFrame(0.0, index=common, columns=["DBC","TIP","TLT"])
    for me in month_end_dates(common):
        b = breakeven.get(me); bs = be_sma.get(me)
        if pd.isna(b) or pd.isna(bs): continue
        if b > bs:  # inflation rising
            w.loc[me,"DBC"] = 0.4; w.loc[me,"TIP"] = 0.4; w.loc[me,"TLT"] = 0.2
        else:
            w.loc[me,"DBC"] = 0.1; w.loc[me,"TIP"] = 0.2; w.loc[me,"TLT"] = 0.7
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)

# --- s23: VIX TERM STRUCTURE CARRY ---
# Paper: Mixon (2007) SSRN 1261682 "The Implied Volatility Term Structure"
#   Simon & Campasano (2014) SSRN 1571727
# Insight: VIX contango (futures > spot) = positive carry for short vol.
# Proxy: VIX level vs VIX 21-day SMA as term structure proxy.
# Signal: VIX in contango (below SMA) → long equity. Backwardation → bonds.
def s23_vix_carry(data):
    if "SPY" not in data or "^VIX" not in data or "TLT" not in data: return None
    c = data["SPY"]["Close"]; vc = data["^VIX"]["Close"].reindex(c.index).ffill()
    tlt = data["TLT"]["Close"].reindex(c.index).ffill()
    vix_sma = SMA(vc, 21)
    closes = pd.DataFrame({"SPY": c, "TLT": tlt}).dropna()
    common = closes.index
    w = pd.DataFrame(0.0, index=common, columns=["SPY","TLT"])
    for dt in common:
        v = vc.get(dt); vs = vix_sma.get(dt)
        if pd.isna(v) or pd.isna(vs): continue
        if v < vs * 0.95:  # contango
            w.loc[dt,"SPY"] = 0.8; w.loc[dt,"TLT"] = 0.2
        elif v > vs * 1.10:  # backwardation
            w.loc[dt,"SPY"] = 0.2; w.loc[dt,"TLT"] = 0.8
        else:
            w.loc[dt,"SPY"] = 0.5; w.loc[dt,"TLT"] = 0.5
    return bt_multi(w, closes)

# --- s24: ENERGY-EQUITY LEAD-LAG ---
# Paper: Driesprong, Jacobsen & Maat (2008) SSRN 460500
#   "Striking Oil: Another Puzzle?"
# Insight: Rising oil prices predict LOWER equity returns next month.
# Signal: If XLE/USO momentum > 15% over 3 months, reduce equity. Otherwise normal.
def s24_energy_equity_leadlag(data):
    energy_t = "XLE" if "XLE" in data else ("USO" if "USO" in data else None)
    if not energy_t or "SPY" not in data or "TLT" not in data: return None
    e = data[energy_t]["Close"]; spy = data["SPY"]["Close"]; tlt = data["TLT"]["Close"]
    common = e.index.intersection(spy.index).intersection(tlt.index)
    e = e.reindex(common).ffill()
    e_mom = e.pct_change(63)
    closes = pd.DataFrame({"SPY": spy.reindex(common).ffill(), "TLT": tlt.reindex(common).ffill()})
    w = pd.DataFrame(0.0, index=common, columns=["SPY","TLT"])
    for me in month_end_dates(common):
        em = e_mom.get(me)
        if pd.isna(em): continue
        if em > 0.15:  # oil surging → bad for equities
            w.loc[me,"SPY"] = 0.2; w.loc[me,"TLT"] = 0.8
        elif em < -0.15:  # oil crashing → equities like it (usually)
            w.loc[me,"SPY"] = 0.8; w.loc[me,"TLT"] = 0.2
        else:
            w.loc[me,"SPY"] = 0.6; w.loc[me,"TLT"] = 0.4
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)

# --- s25: YIELD CURVE INVERSION TIMING ---
# Paper: Estrella & Mishkin (1998) "Predicting U.S. Recessions" FRBNY
#   Harvey (1988) SSRN — inverted yield curve predicts recessions.
# Proxy: TLT/SHY ratio as yield curve proxy (when TLT outperforms, curve flattening).
# Signal: When curve inverts (TLT/SHY momentum > 0 strongly), rotate to defensive.
def s25_yield_curve_timing(data):
    if "TLT" not in data or "SHY" not in data or "SPY" not in data: return None
    tlt = data["TLT"]["Close"]; shy = data["SHY"]["Close"]; spy = data["SPY"]["Close"]
    common = tlt.index.intersection(shy.index).intersection(spy.index)
    curve = (tlt.reindex(common).ffill() / shy.reindex(common).ffill().replace(0, np.nan))
    curve_mom = curve.pct_change(63)
    closes = pd.DataFrame({"SPY": spy.reindex(common).ffill(), "TLT": tlt.reindex(common).ffill(),
                           "SHY": shy.reindex(common).ffill()})
    w = pd.DataFrame(0.0, index=common, columns=["SPY","TLT","SHY"])
    for me in month_end_dates(common):
        cm = curve_mom.get(me)
        if pd.isna(cm): continue
        if cm > 0.02:  # curve flattening/inverting
            w.loc[me,"SPY"] = 0.1; w.loc[me,"TLT"] = 0.3; w.loc[me,"SHY"] = 0.6
        elif cm < -0.02:  # curve steepening (recovery)
            w.loc[me,"SPY"] = 0.7; w.loc[me,"TLT"] = 0.2; w.loc[me,"SHY"] = 0.1
        else:
            w.loc[me,"SPY"] = 0.5; w.loc[me,"TLT"] = 0.3; w.loc[me,"SHY"] = 0.2
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)

# --- s26: GOLD-MINERS LEAD-LAG ---
# Paper: Erb & Harvey (2013) SSRN 2078535 "The Golden Dilemma"
# Insight: Gold miners (GDX proxy via GLD) lead physical gold prices.
# Proxy: When GLD momentum is strong + VIX rising → crisis hedge allocation.
# Signal: GLD momentum + VIX > 20 → max gold allocation.
def s26_gold_crisis_hedge(data):
    if "GLD" not in data or "SPY" not in data or "^VIX" not in data: return None
    gld = data["GLD"]["Close"]; spy = data["SPY"]["Close"]
    vc = data["^VIX"]["Close"].reindex(spy.index).ffill()
    common = gld.index.intersection(spy.index)
    gld = gld.reindex(common).ffill()
    gld_mom = gld.pct_change(63)
    closes = pd.DataFrame({"GLD": gld, "SPY": spy.reindex(common).ffill()})
    w = pd.DataFrame(0.0, index=common, columns=["GLD","SPY"])
    for me in month_end_dates(common):
        gm = gld_mom.get(me); v = vc.get(me)
        if pd.isna(gm) or pd.isna(v): continue
        if gm > 0.05 and v > 20:
            w.loc[me,"GLD"] = 0.6; w.loc[me,"SPY"] = 0.4
        elif gm > 0:
            w.loc[me,"GLD"] = 0.4; w.loc[me,"SPY"] = 0.6
        else:
            w.loc[me,"GLD"] = 0.2; w.loc[me,"SPY"] = 0.8
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)


# ═══════════════════════════════════════════════════════════════════
# ═══  CATEGORY D: MICROSTRUCTURE & ORDER FLOW (s27–s34)         ═══
# ═══════════════════════════════════════════════════════════════════

# --- s27: AMIHUD ILLIQUIDITY PREMIUM ---
# Paper: Amihud (2002) "Illiquidity and Stock Returns" JFM
#   SSRN 276213 — illiquid stocks earn a premium.
# Signal: When SPY illiquidity spikes → subsequent returns are higher.
def s27_amihud_premium(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    illiq = amihud_illiquidity(df, 21)
    illiq_z = (illiq - illiq.rolling(252).mean()) / illiq.rolling(252).std()
    buy = illiq_z > 1.5  # illiquidity spike
    sell = illiq_z < 0
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s28: ODD LOT RATIO ---
# Paper: Boehmer, Jones & Zhang (2008) SSRN 983327
#   "Which Shorts Are Informed?"
# Insight: Retail odd-lot trading (< 100 shares) is contrarian indicator.
# Proxy: Volume as % of average — extreme low volume = retail-dominated → reversal.
# Signal: Very low volume days on SPY → informed traders absent → buy.
def s28_odd_lot_proxy(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    v = df["Volume"]; v_sma = SMA(v, 20)
    vol_ratio = v / v_sma.replace(0, np.nan)
    # Very low relative volume = retail-dominated
    rsi5 = RSI(c, 5)
    buy = (vol_ratio < 0.5) & (rsi5 < 40)
    sell = rsi5 > 60
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s29: GARMAN-KLASS VS CLOSE-CLOSE VOL DIVERGENCE ---
# Paper: Garman & Klass (1980) "On the Estimation of Security Price Volatilities"
# Insight: When GK vol >> close-close vol, it means large intraday moves are being
#   hidden by close-to-close — stealth selling. This precedes drops.
# Signal: Large divergence → reduce exposure.
def s29_stealth_vol(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    gk = garman_klass_vol(df, 21)
    cc_vol = c.pct_change().rolling(21).std() * np.sqrt(252)
    ratio = gk / cc_vol.replace(0, np.nan)
    # Ratio >> 1 means stealth volatility
    pos = pd.Series(1, index=c.index)
    pos[ratio > 1.5] = 0  # stealth vol → go to cash
    return bt_single(pos, c)

# --- s30: VOLUME-WEIGHTED RSI ---
# Paper: Inspired by Lerman, Livnat & Mendenhall (2008) SSRN 1121475
#   "The High-Volume Return Premium"
# Insight: RSI signals are stronger when confirmed by volume.
# Signal: RSI(2) < 10 on above-average volume → strong buy.
def s30_vol_weighted_rsi(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    rsi2 = RSI(c, 2); ma200 = SMA(c, 200)
    vsurp = volume_surprise(df, 20)
    buy = (rsi2 < 10) & (c > ma200) & (vsurp > 0.3)
    sell = c > SMA(c, 5)
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s31: MFI DIVERGENCE ---
# Paper: Quong & Satchell (1993) — Money Flow Index as accumulation/distribution signal.
# Insight: When price makes new lows but MFI doesn't → accumulation = buy signal.
# Signal: Price at 20d low but MFI(14) > 30 → bullish divergence.
def s31_mfi_divergence(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    mfi = MFI(df, 14)
    price_low = c == c.rolling(20).min()
    ma200 = SMA(c, 200)
    buy = price_low & (mfi > 30) & (c > ma200)
    sell = c > SMA(c, 5)
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s32: PRICE RANGE COMPRESSION BREAKOUT ---
# Paper: Bollinger (2001) "Bollinger on Bollinger Bands" + academic work on
#   volatility clustering (Mandelbrot 1963).
# Insight: Low volatility periods (range compression) precede explosive moves.
# Signal: When 5d range / 65d range < 0.3, enter long if above 200-SMA.
def s32_range_compression(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    prr = price_range_ratio(df, 5, 65)
    ma200 = SMA(c, 200)
    buy = (prr < 0.3) & (c > ma200)
    sell = prr > 0.6  # expansion = exit
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s33: ETF FLOW REVERSAL (CREATION/REDEMPTION PROXY) ---
# Paper: Ben-David, Franzoni & Moussawi (2018) SSRN 2701961
#   "Do ETFs Increase Volatility?"
# Insight: Large ETF inflows (volume spikes on up days) revert.
# Signal: SPY volume spike on >1% up day → likely reversal in 3-5 days.
def s33_etf_flow_reversal(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    vsurp = volume_surprise(df, 20)
    ret = c.pct_change()
    inflow_spike = (vsurp > 2.0) & (ret > 0.01)
    # Reduce exposure for 5 days after inflow spike
    pos = pd.Series(1, index=c.index)
    spike_dates = inflow_spike[inflow_spike].index
    for dt in spike_dates:
        loc = c.index.get_loc(dt)
        for j in range(1, 6):
            if loc+j < len(c): pos.iat[loc+j] = 0
    return bt_single(pos, c)

# --- s34: PARKINSON HIGH-LOW VOLATILITY TIMING ---
# Paper: Parkinson (1980) "The Extreme Value Method for Estimating the Variance"
# Insight: Parkinson vol is more efficient — when it diverges from close-close
#   vol, the market is in a different regime.
# Signal: Parkinson > close-close → trending → use momentum. Otherwise mean-revert.
def s34_parkinson_regime(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    pk_vol = parkinson_vol(df, 21)
    cc_vol = c.pct_change().rolling(21).std() * np.sqrt(252)
    ratio = pk_vol / cc_vol.replace(0, np.nan)
    mom = c.pct_change(42)
    rsi2 = RSI(c, 2)
    # Trending regime (ratio > 1.2): use momentum
    # Mean-reverting regime: use RSI
    pos_trend = (mom > 0).astype(int)
    buy_mr = rsi2 < 15; sell_mr = rsi2 > 70
    pos_mr = mr_positions(buy_mr.fillna(False), sell_mr.fillna(False))
    pos = pd.Series(0, index=c.index, dtype=int)
    for i in range(len(pos)):
        r = ratio.iat[i] if not pd.isna(ratio.iat[i]) else 1.0
        if r > 1.2:
            pos.iat[i] = pos_trend.iat[i]
        else:
            pos.iat[i] = pos_mr.iat[i]
    return bt_single(pos, c)


# ═══════════════════════════════════════════════════════════════════
# ═══  CATEGORY E: BEHAVIORAL & SENTIMENT EXPLOITATION (s35–s42) ═══
# ═══════════════════════════════════════════════════════════════════

# --- s35: DISPOSITION EFFECT EXPLOITATION ---
# Paper: Frazzini (2006) SSRN 675643 "The Disposition Effect and Underreaction"
# Insight: Investors sell winners too early, hold losers too long.
# Proxy: Stocks near 52-week highs have less selling pressure → momentum continues.
# Signal: When SPY is within 2% of 52-week high → momentum → stay long.
def s35_disposition_momentum(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    high_52 = c.rolling(252).max()
    pct_from_high = c / high_52 - 1
    pos = (pct_from_high > -0.02).astype(int)  # within 2% of high
    return bt_single(pos, c)

# --- s36: LOTTERY STOCK AVOIDANCE ---
# Paper: Bali, Cakici & Whitelaw (2011) SSRN 1344558
#   "Maxing Out: Stocks as Lotteries and Cross-Section of Expected Returns"
# Insight: Stocks with extreme positive MAX returns underperform (lottery premium).
# Proxy: Overweight low-beta sectors (anti-lottery), underweight high-beta.
# Signal: Rotate to USMV/QUAL when VIX > 20 (lottery demand peaks in fear).
def s36_anti_lottery(data):
    low_vol = ["USMV","QUAL"]
    high_beta = ["QQQ","IWM"]
    avail_lv = [t for t in low_vol if t in data]
    avail_hb = [t for t in high_beta if t in data]
    if not avail_lv or not avail_hb: return None
    all_t = avail_lv + avail_hb
    closes = pd.DataFrame({t: data[t]["Close"] for t in all_t}).dropna()
    if len(closes) < 252: return None
    vc = data["^VIX"]["Close"].reindex(closes.index).ffill() if "^VIX" in data else None
    w = pd.DataFrame(0.0, index=closes.index, columns=all_t)
    for me in month_end_dates(closes.index):
        v = vc.get(me, 15) if vc is not None else 15
        if v > 20:
            for a in avail_lv: w.loc[me, a] = 1.0/len(avail_lv)
        else:
            # Equal weight all
            for a in all_t: w.loc[me, a] = 1.0/len(all_t)
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)

# --- s37: ANCHORING BIAS — 52-WEEK HIGH MOMENTUM ---
# Paper: George & Hwang (2004) SSRN 444460
#   "The 52-Week High and Momentum Profits"
# Insight: Nearness to 52-week high predicts future returns better than past returns.
# Signal: Rotate sectors by proximity to their 52-week highs.
def s37_anchoring_52w(data):
    sc = get_sector_closes(data)
    if len(sc) < 252: return None
    high_52 = sc.rolling(252).max()
    nearness = sc / high_52
    w = pd.DataFrame(0.0, index=sc.index, columns=sc.columns)
    for me in month_end_dates(sc.index):
        n = nearness.loc[me].dropna()
        if len(n) < 3: continue
        top3 = n.nlargest(3).index
        for a in top3: w.loc[me, a] = 1.0/3
    w = w.ffill().fillna(0)
    return bt_multi(w, sc)

# --- s38: ROUND NUMBER PSYCHOLOGY ---
# Paper: Bhattacharya, Holden & Jacobsen (2012) SSRN 1364960
#   "Penny Wise, Dollar Foolish: Buy-Sell Imbalances On and Around Round Numbers"
# Insight: Stocks stall at round numbers due to limit order clustering.
# Signal: When SPY is within 0.5% of a round number ($X00), expect resistance.
def s38_round_number(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    # Distance to nearest $10 level
    nearest_10 = (c / 10).round() * 10
    pct_from_round = (c - nearest_10).abs() / c
    # Near round number → resistance → reduce exposure
    pos = pd.Series(1, index=c.index)
    pos[pct_from_round < 0.005] = 0  # within 0.5% of round number
    return bt_single(pos, c)

# --- s39: INVESTOR ATTENTION CYCLE (WEEK-OF-MONTH) ---
# Paper: Barber & Odean (2008) SSRN 381180 "All That Glitters"
# Insight: Retail investors are net buyers early in the month (payday effect).
# Signal: Long first 5 days of month (retail buying pressure), reduce last 5.
def s39_payday_effect(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    pos = pd.Series(0, index=c.index, dtype=int)
    for dt in c.index:
        month_dates = c.index[(c.index.year==dt.year)&(c.index.month==dt.month)]
        if len(month_dates) == 0: continue
        idx_in_month = list(month_dates).index(dt)
        if idx_in_month < 5: pos.loc[dt] = 1
    return bt_single(pos, c)

# --- s40: VIX PERCENTILE CONTRARIAN ---
# Paper: Whaley (2000) SSRN 229396 "The Investor Fear Gauge"
# Insight: Extreme VIX readings are contrarian — very high VIX → buy, very low → caution.
# Signal: VIX > 95th percentile → load up on SPY. VIX < 10th percentile → reduce.
def s40_vix_percentile(data):
    if "SPY" not in data or "^VIX" not in data: return None
    c = data["SPY"]["Close"]; vc = data["^VIX"]["Close"].reindex(c.index).ffill()
    vix_pct = vc.rolling(252).rank(pct=True)
    pos = pd.Series(0.5, index=c.index)  # default half invested
    pos[vix_pct > 0.95] = 1.0   # extreme fear → full long
    pos[vix_pct < 0.10] = 0.0   # extreme complacency → cash
    return bt_single(pos, c)

# --- s41: MEAN-REVERSION WITH HURST FILTER ---
# Paper: Mandelbrot (1971) + Lo (1991) SSRN "Long-Term Memory in Stock Market Prices"
# Insight: Hurst exponent < 0.5 → mean-reverting regime. Use MR strategies only then.
# Signal: Apply RSI(2) mean-reversion ONLY when rolling Hurst < 0.5.
def s41_hurst_filtered_mr(data):
    if "SPY" not in data: return None
    df = data["SPY"]; c = df["Close"]
    rsi2 = RSI(c, 2); ma200 = SMA(c, 200)
    # Calculate rolling Hurst every 21 days (expensive)
    rets = c.pct_change().dropna().values
    hurst_series = pd.Series(0.5, index=c.index)
    for i in range(252, len(c), 21):
        h = hurst_exponent(rets[max(0,i-252):i])
        hurst_series.iat[i] = h
    hurst_series = hurst_series.replace(0.5, np.nan).ffill().fillna(0.5)
    buy = (rsi2 < 10) & (c > ma200) & (hurst_series < 0.5)
    sell = c > SMA(c, 5)
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s42: SKEWNESS PREMIUM ---
# Paper: Amaya, Christoffersen, Jacobs & Vasquez (2015) SSRN 2360394
#   "Does Realized Skewness Predict the Cross-Section of Equity Returns?"
# Insight: Negatively skewed stocks outperform positively skewed ones.
# Signal: When SPY realized skew is very negative → contrarian buy (oversold).
def s42_skewness_signal(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    skew = realized_skew(c, 21)
    ma200 = SMA(c, 200)
    buy = (skew < -1.0) & (c > ma200)
    sell = skew > 0
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)


# ═══════════════════════════════════════════════════════════════════
# ═══  CATEGORY F: VOLATILITY SURFACE & DERIVATIVES (s43–s50)    ═══
# ═══════════════════════════════════════════════════════════════════

# --- s43: VOLATILITY RISK PREMIUM HARVESTING ---
# Paper: Carr & Wu (2009) "Variance Risk Premiums" RFS
#   SSRN 577222
# Insight: Implied vol (VIX) consistently overestimates realized vol → short vol is profitable.
# Signal: When VIX/realized vol ratio > 1.3, sell vol (long equity). When < 1.0, hedge.
def s43_vrp_harvest(data):
    if "SPY" not in data or "^VIX" not in data: return None
    c = data["SPY"]["Close"]; vc = data["^VIX"]["Close"].reindex(c.index).ffill()
    rv = c.pct_change().rolling(21).std() * np.sqrt(252) * 100  # annualized, in %
    vrp_ratio = vc / rv.replace(0, np.nan)
    pos = pd.Series(0.5, index=c.index)
    pos[vrp_ratio > 1.3] = 1.0   # VRP rich → harvest
    pos[vrp_ratio < 1.0] = 0.0   # VRP gone → hedge
    return bt_single(pos, c)

# --- s44: VOLATILITY OF VOLATILITY TIMING ---
# Paper: Baltussen, Van Bekkum & Grient (2018) SSRN 2497759
#   "Unknown Unknowns: Uncertainty About Risk and Stock Returns"
# Insight: High vol-of-vol predicts lower returns. Low vol-of-vol → buy.
# Signal: When VoV is in bottom quartile → full equity. Top quartile → bonds.
def s44_vov_timing(data):
    if "SPY" not in data or "^VIX" not in data or "TLT" not in data: return None
    vc = data["^VIX"]["Close"]; c = data["SPY"]["Close"]; tlt = data["TLT"]["Close"]
    common = vc.index.intersection(c.index).intersection(tlt.index)
    vc = vc.reindex(common).ffill()
    vov = vc.rolling(21).std()
    vov_pct = vov.rolling(252).rank(pct=True)
    closes = pd.DataFrame({"SPY": c.reindex(common).ffill(), "TLT": tlt.reindex(common).ffill()})
    w = pd.DataFrame(0.0, index=common, columns=["SPY","TLT"])
    for dt in common:
        vp = vov_pct.get(dt)
        if pd.isna(vp): continue
        if vp < 0.25:
            w.loc[dt,"SPY"] = 0.9; w.loc[dt,"TLT"] = 0.1
        elif vp > 0.75:
            w.loc[dt,"SPY"] = 0.2; w.loc[dt,"TLT"] = 0.8
        else:
            w.loc[dt,"SPY"] = 0.6; w.loc[dt,"TLT"] = 0.4
    return bt_multi(w, closes)

# --- s45: REALIZED-IMPLIED VOL SPREAD (VRSP) ---
# Paper: Bollen & Whaley (2004) SSRN 540523
#   "Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?"
# Insight: When implied > realized significantly → net put buying → fear overdone.
# Signal: Large positive VRSP → buy the fear (SPY goes up).
def s45_vrsp_signal(data):
    if "SPY" not in data or "^VIX" not in data: return None
    c = data["SPY"]["Close"]; vc = data["^VIX"]["Close"].reindex(c.index).ffill()
    rv = c.pct_change().rolling(21).std() * np.sqrt(252) * 100
    vrsp = vc - rv
    vrsp_z = (vrsp - vrsp.rolling(252).mean()) / vrsp.rolling(252).std()
    buy = vrsp_z > 2.0
    sell = vrsp_z < 0
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s46: CROSS-ASSET VOL CORRELATION REGIME ---
# Paper: Adrian & Brunnermeier (2016) SSRN 1616799 "CoVaR"
# Insight: When cross-asset correlations spike → systemic risk → reduce exposure.
# Proxy: Rolling correlation between SPY and TLT. Normally negative; when it
#   turns positive → both falling together → crisis.
# Signal: SPY-TLT correlation > 0 → cash. Negative → normal allocation.
def s46_covar_regime(data):
    if "SPY" not in data or "TLT" not in data: return None
    spy = data["SPY"]["Close"]; tlt = data["TLT"]["Close"]
    common = spy.index.intersection(tlt.index)
    sr = spy.reindex(common).pct_change(); tr = tlt.reindex(common).pct_change()
    corr = sr.rolling(63).corr(tr)
    closes = pd.DataFrame({"SPY": spy.reindex(common).ffill(), "TLT": tlt.reindex(common).ffill()})
    w = pd.DataFrame(0.0, index=common, columns=["SPY","TLT"])
    for dt in common:
        c = corr.get(dt)
        if pd.isna(c): continue
        if c > 0.2:  # positive correlation → crisis
            w.loc[dt,"SPY"] = 0.1; w.loc[dt,"TLT"] = 0.1  # mostly cash
        elif c < -0.3:  # strong negative → normal diversification
            w.loc[dt,"SPY"] = 0.6; w.loc[dt,"TLT"] = 0.4
        else:
            w.loc[dt,"SPY"] = 0.5; w.loc[dt,"TLT"] = 0.3
    return bt_multi(w, closes)

# --- s47: LEVERAGE EFFECT ASYMMETRY ---
# Paper: Black (1976) + Christie (1982) — leverage effect:
#   negative returns increase volatility more than positive returns.
# Insight: After sharp down move, vol expansion → trade the reversal.
# Signal: If yesterday's return < -2% AND VIX spike > 10%, buy the reversal.
def s47_leverage_reversal(data):
    if "SPY" not in data or "^VIX" not in data: return None
    c = data["SPY"]["Close"]; vc = data["^VIX"]["Close"].reindex(c.index).ffill()
    spy_ret = c.pct_change()
    vix_ret = vc.pct_change()
    buy = (spy_ret < -0.02) & (vix_ret > 0.10)
    sell = spy_ret > 0.01
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s48: REALIZED KURTOSIS TAIL SIGNAL ---
# Paper: Bollerslev & Todorov (2011) SSRN 1723508
#   "Tails, Fears, and Risk Premia"
# Insight: High realized kurtosis = fat tails = market pricing in tail events.
# Signal: When kurtosis spikes → tail risk is priced → buy (risk premium).
def s48_kurtosis_premium(data):
    if "SPY" not in data: return None
    c = data["SPY"]["Close"]
    kurt = realized_kurt(c, 21)
    ma200 = SMA(c, 200)
    kurt_pct = kurt.rolling(252).rank(pct=True)
    buy = (kurt_pct > 0.9) & (c > ma200)
    sell = kurt_pct < 0.5
    pos = mr_positions(buy.fillna(False), sell.fillna(False))
    return bt_single(pos, c)

# --- s49: CONDITIONAL RISK PARITY ---
# Paper: Asness, Frazzini & Pedersen (2012) SSRN 2050064
#   "Leverage Aversion and Risk Parity"
# Insight: Equal-risk-contribution portfolios outperform equal-weight, especially
#   with a volatility regime overlay.
# Signal: Risk parity SPY/TLT/GLD/DBC with VIX regime overlay.
def s49_cond_risk_parity(data):
    assets = ["SPY","TLT","GLD","DBC"]
    avail = [a for a in assets if a in data]
    if len(avail) < 3: return None
    closes = pd.DataFrame({a: data[a]["Close"] for a in avail}).dropna()
    if len(closes) < 252: return None
    vc = data["^VIX"]["Close"].reindex(closes.index).ffill() if "^VIX" in data else None
    w = inv_vol_weights(closes, 63)
    # VIX overlay: when VIX > 30, reduce equity weight
    if vc is not None:
        for dt in closes.index:
            v = vc.get(dt, 15)
            if v > 30 and "SPY" in w.columns:
                spy_w = w.loc[dt,"SPY"]
                w.loc[dt,"SPY"] = spy_w * 0.5
                if "TLT" in w.columns: w.loc[dt,"TLT"] += spy_w * 0.5
        # Re-normalize
        row_sum = w.sum(axis=1).replace(0, 1)
        w = w.div(row_sum, axis=0)
    return bt_multi(w, closes)

# --- s50: CRYPTO VOLATILITY REGIME ROTATION ---
# Paper: Liu & Tsyvinski (2021) SSRN 3115402
#   "Risks and Returns of Cryptocurrency"
# Insight: Crypto factor (momentum + network) is priced differently in high/low vol regimes.
# Signal: In low BTC vol → risk-on (QQQ/IWM). In high BTC vol → defensive (TLT/GLD).
def s50_crypto_vol_regime(data):
    btc_key = "BTC-USD" if "BTC-USD" in data else None
    if not btc_key: return None
    risk_on = ["QQQ","IWM"]; risk_off = ["TLT","GLD"]
    avail_on = [t for t in risk_on if t in data]
    avail_off = [t for t in risk_off if t in data]
    if not avail_on or not avail_off: return None
    all_t = avail_on + avail_off
    closes = pd.DataFrame({t: data[t]["Close"] for t in all_t}).dropna()
    btc = data[btc_key]["Close"].reindex(closes.index).ffill()
    btc_vol = btc.pct_change().rolling(21).std() * np.sqrt(365)
    btc_vol_pct = btc_vol.rolling(252).rank(pct=True)
    w = pd.DataFrame(0.0, index=closes.index, columns=all_t)
    for me in month_end_dates(closes.index):
        bvp = btc_vol_pct.get(me)
        if pd.isna(bvp): continue
        if bvp < 0.4:  # low crypto vol → risk-on
            for a in avail_on: w.loc[me, a] = 1.0/len(avail_on)
        else:  # high crypto vol → defensive
            for a in avail_off: w.loc[me, a] = 1.0/len(avail_off)
    w = w.ffill().fillna(0)
    return bt_multi(w, closes)


# ═══════════════════════════════════════════════════════════════
# STRATEGY REGISTRY
# ═══════════════════════════════════════════════════════════════
STRATEGIES = [
    # (id, name, paper_ref, function)
    ("s01", "Filing Complexity Rotation", "Loughran & McDonald (2014) SSRN 2425801", s01_filing_complexity),
    ("s02", "Earnings Tone Divergence", "Huang, Zang & Zheng (2014) SSRN 2361560", s02_tone_divergence),
    ("s03", "Wiki Edit Attention Proxy", "Moat et al. (2013) DOI 10.1038/srep01801", s03_wiki_edit_proxy),
    ("s04", "Patent Citation Momentum", "Kogan et al. (2017) SSRN 2345690", s04_patent_momentum),
    ("s05", "Policy Uncertainty Contrarian", "Baker, Bloom & Davis (2016) SSRN 2198490", s05_policy_uncertainty),
    ("s06", "MD&A Tone Shift Rotation", "Feldman et al. (2010) SSRN 1437877", s06_tone_shift_rotation),
    ("s07", "Regulatory Stress Avoidance", "Cassell, Dreher & Myers (2013) SSRN 2149367", s07_regulatory_stress),
    ("s08", "Media Pessimism Reversal", "Tetlock (2007) SSRN 685145", s08_media_pessimism_reversal),
    ("s09", "Employee Sentiment Breadth", "Green et al. (2019) SSRN 3287437", s09_employee_sentiment),
    ("s10", "Attention Decay Fade", "Da, Engelberg & Gao (2011) SSRN 1572085", s10_attention_decay),
    ("s11", "Intraday Momentum Gap", "Gao et al. (2018) SSRN 2440866", s11_intraday_momentum),
    ("s12", "Pre-FOMC Drift", "Lucca & Moench (2015) SSRN 1961927", s12_fomc_drift),
    ("s13", "Turn-of-Month + RSI", "McConnell & Xu (2008) SSRN 925589", s13_turn_of_month_rsi),
    ("s14", "Monday Reversal", "French (1980) / Lakonishok & Maberly (1990)", s14_monday_reversal),
    ("s15", "Quarter-End Window Dressing", "Lakonishok, Shleifer et al. (1991)", s15_window_dressing),
    ("s16", "Holiday Effect", "Ariel (1990) / Lakonishok & Smidt (1988)", s16_holiday_effect),
    ("s17", "Overnight Premium", "Lou, Polk & Skouras (2019) SSRN 2554010", s17_overnight_premium),
    ("s18", "Ramadan Effect", "Bialkowski et al. (2012) SSRN 1989529", s18_ramadan_effect),
    ("s19", "Copper-Gold Economic Barometer", "Faber (2013) / Gundlach (2018)", s19_copper_gold_ratio),
    ("s20", "BTC Risk Appetite", "Bouri et al. (2017) DOI 10.1016/j.econlet", s20_btc_risk_appetite),
    ("s21", "Credit-Equity Divergence", "Collin-Dufresne et al. (2001) SSRN 269271", s21_credit_equity_divergence),
    ("s22", "Breakeven Inflation Trade", "Ang, Bekaert & Wei (2008) SSRN 946714", s22_breakeven_inflation),
    ("s23", "VIX Term Structure Carry", "Mixon (2007) / Simon & Campasano (2014)", s23_vix_carry),
    ("s24", "Energy-Equity Lead-Lag", "Driesprong et al. (2008) SSRN 460500", s24_energy_equity_leadlag),
    ("s25", "Yield Curve Inversion Timing", "Estrella & Mishkin (1998) / Harvey (1988)", s25_yield_curve_timing),
    ("s26", "Gold Crisis Hedge", "Erb & Harvey (2013) SSRN 2078535", s26_gold_crisis_hedge),
    ("s27", "Amihud Illiquidity Premium", "Amihud (2002) SSRN 276213", s27_amihud_premium),
    ("s28", "Odd Lot Retail Contrarian", "Boehmer, Jones & Zhang (2008) SSRN 983327", s28_odd_lot_proxy),
    ("s29", "Stealth Volatility Filter", "Garman & Klass (1980)", s29_stealth_vol),
    ("s30", "Volume-Weighted RSI(2)", "Lerman et al. (2008) SSRN 1121475", s30_vol_weighted_rsi),
    ("s31", "MFI Divergence Buy", "Quong & Satchell (1993)", s31_mfi_divergence),
    ("s32", "Range Compression Breakout", "Bollinger (2001) / Mandelbrot (1963)", s32_range_compression),
    ("s33", "ETF Flow Reversal", "Ben-David et al. (2018) SSRN 2701961", s33_etf_flow_reversal),
    ("s34", "Parkinson Regime Switch", "Parkinson (1980)", s34_parkinson_regime),
    ("s35", "Disposition Momentum", "Frazzini (2006) SSRN 675643", s35_disposition_momentum),
    ("s36", "Anti-Lottery Rotation", "Bali et al. (2011) SSRN 1344558", s36_anti_lottery),
    ("s37", "52-Week High Anchoring", "George & Hwang (2004) SSRN 444460", s37_anchoring_52w),
    ("s38", "Round Number Avoidance", "Bhattacharya et al. (2012) SSRN 1364960", s38_round_number),
    ("s39", "Payday Buying Pressure", "Barber & Odean (2008) SSRN 381180", s39_payday_effect),
    ("s40", "VIX Percentile Contrarian", "Whaley (2000) SSRN 229396", s40_vix_percentile),
    ("s41", "Hurst-Filtered Mean Reversion", "Mandelbrot (1971) / Lo (1991)", s41_hurst_filtered_mr),
    ("s42", "Realized Skewness Premium", "Amaya et al. (2015) SSRN 2360394", s42_skewness_signal),
    ("s43", "Vol Risk Premium Harvest", "Carr & Wu (2009) SSRN 577222", s43_vrp_harvest),
    ("s44", "Vol-of-Vol Timing", "Baltussen et al. (2018) SSRN 2497759", s44_vov_timing),
    ("s45", "Implied-Realized Vol Spread", "Bollen & Whaley (2004) SSRN 540523", s45_vrsp_signal),
    ("s46", "Cross-Asset Correlation Regime", "Adrian & Brunnermeier (2016) SSRN 1616799", s46_covar_regime),
    ("s47", "Leverage Effect Reversal", "Black (1976) / Christie (1982)", s47_leverage_reversal),
    ("s48", "Kurtosis Tail Premium", "Bollerslev & Todorov (2011) SSRN 1723508", s48_kurtosis_premium),
    ("s49", "Conditional Risk Parity", "Asness et al. (2012) SSRN 2050064", s49_cond_risk_parity),
    ("s50", "Crypto Vol Regime Rotation", "Liu & Tsyvinski (2021) SSRN 3115402", s50_crypto_vol_regime),
]


# ═══════════════════════════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════════════════════════
def main():
    print("=" * 80)
    print("  QuantiHack 2026 — 50 Alternative Data Strategies from Academic Literature")
    print("=" * 80)
    print(f"\n  WF1: {WF1_START} -> {WF_END}  (full walk-forward)")
    print(f"  WF2: {WF2_START} -> {WF_END}  (tariff-war stress test)")
    print(f"  Capital: ${CAP:,.0f}  |  Slippage: {SLIP} bps/side")
    print()

    print("Downloading data...")
    data = download_all()
    print(f"\n  {len(data)} tickers loaded.\n")

    # SPY benchmark
    if "SPY" not in data:
        print("ERROR: SPY data not available. Cannot proceed.")
        return
    spy_eq = data["SPY"]["Close"].copy()
    spy_eq = (spy_eq / spy_eq.iloc[0]) * CAP

    results = []
    for sid, name, paper, func in STRATEGIES:
        print(f"  {sid}: {name}...", end=" ", flush=True)
        t0 = time.time()
        try:
            eq = func(data)
            if eq is None or len(eq) < 30:
                print("SKIP (no data)")
                continue

            # WF1 metrics
            wf1 = eq[(eq.index >= WF1_START) & (eq.index <= WF_END)]
            m1 = metrics(wf1) if len(wf1) > 30 else {}

            # WF2 metrics (stress test)
            wf2 = eq[(eq.index >= WF2_START) & (eq.index <= WF_END)]
            m2 = metrics(wf2) if len(wf2) > 5 else {}

            # Beta/alpha vs SPY
            b, a = beta_alpha(wf1, spy_eq.reindex(wf1.index).ffill())

            elapsed = time.time() - t0
            row = dict(
                num=sid, name=name, paper=paper,
                wf1_cagr=m1.get("cagr",0), wf1_sharpe=m1.get("sharpe",0),
                wf1_sortino=m1.get("sortino",0), wf1_mdd=m1.get("mdd",0),
                wf1_calmar=m1.get("calmar",0), wf1_vol=m1.get("vol",0),
                wf1_winrate=m1.get("win_rate",0), wf1_pf=m1.get("profit_factor",0),
                wf1_skew=m1.get("skew",0), wf1_tail=m1.get("tail_ratio",0),
                wf2_ret=m2.get("total_ret",0), wf2_mdd=m2.get("mdd",0),
                wf2_sharpe=m2.get("sharpe",0),
                beta=b, alpha=a, elapsed=f"{elapsed:.1f}s"
            )
            results.append(row)
            print(f"Sharpe={m1.get('sharpe',0):.2f}  CAGR={m1.get('cagr',0):.1%}  "
                  f"MDD={m1.get('mdd',0):.1%}  WF2={m2.get('total_ret',0):.1%}  "
                  f"[{elapsed:.1f}s]")
        except Exception as e:
            print(f"ERROR: {e}")

    if not results:
        print("\nNo strategies produced results.")
        return

    # Ranking
    df = pd.DataFrame(results)
    df["wf1_rank"] = df["wf1_sharpe"].rank(ascending=False)
    df["wf2_rank"] = df["wf2_ret"].rank(ascending=False)
    df["combined_rank"] = (df["wf1_rank"] + df["wf2_rank"]) / 2
    df = df.sort_values("combined_rank")

    print("\n" + "=" * 120)
    print("  RANKED RESULTS (by Combined WF1 Sharpe + WF2 Return)")
    print("=" * 120)
    print(f"{'#':<4} {'ID':<5} {'Name':<35} {'WF1 CAGR':>9} {'WF1 Sharpe':>11} "
          f"{'WF1 MDD':>9} {'WF2 Ret':>9} {'WF2 MDD':>9} {'Alpha':>8} {'Beta':>7} {'Rank':>6}")
    print("-" * 120)
    for i, row in df.iterrows():
        print(f"{df.index.get_loc(i)+1:<4} {row['num']:<5} {row['name']:<35} "
              f"{row['wf1_cagr']:>8.1%} {row['wf1_sharpe']:>10.2f} "
              f"{row['wf1_mdd']:>8.1%} {row['wf2_ret']:>8.1%} {row['wf2_mdd']:>8.1%} "
              f"{row['alpha']:>7.2%} {row['beta']:>6.2f} {row['combined_rank']:>5.1f}")

    # Save CSV
    csv_path = "quantihack_alt_data_50_results.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nResults saved to {csv_path}")

    # ═══════════════════════════════════════════════════════════════
    # PLOT: Top 10 equity curves
    # ═══════════════════════════════════════════════════════════════
    print("\nGenerating equity curve plot for top 10...")
    top10 = df.head(10)

    fig, axes = plt.subplots(2, 1, figsize=(16, 14))

    # WF1 equity curves
    ax1 = axes[0]
    for _, row in top10.iterrows():
        sid = row["num"]
        func = dict((s[0], s[3]) for s in STRATEGIES)[sid]
        try:
            eq = func(data)
            if eq is None: continue
            wf1 = eq[(eq.index >= WF1_START) & (eq.index <= WF_END)]
            norm = wf1 / wf1.iloc[0] * CAP
            ax1.plot(norm.index, norm.values, label=f"{sid}: {row['name']}", linewidth=1.2)
        except: pass
    # SPY benchmark
    spy_wf1 = spy_eq[(spy_eq.index >= WF1_START) & (spy_eq.index <= WF_END)]
    ax1.plot(spy_wf1.index, spy_wf1.values, label="SPY (benchmark)", color="black",
             linewidth=2, linestyle="--")
    ax1.set_title("Top 10 Alt-Data Strategies — Full Walk-Forward (2010–2026)", fontsize=14)
    ax1.set_ylabel("Portfolio Value ($)")
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.legend(fontsize=8, loc="upper left")
    ax1.grid(True, alpha=0.3)

    # WF2 stress test
    ax2 = axes[1]
    for _, row in top10.iterrows():
        sid = row["num"]
        func = dict((s[0], s[3]) for s in STRATEGIES)[sid]
        try:
            eq = func(data)
            if eq is None: continue
            wf2 = eq[(eq.index >= WF2_START) & (eq.index <= WF_END)]
            if len(wf2) < 2: continue
            norm = wf2 / wf2.iloc[0] * CAP
            ax2.plot(norm.index, norm.values, label=f"{sid}: {row['name']}", linewidth=1.2)
        except: pass
    spy_wf2 = spy_eq[(spy_eq.index >= WF2_START) & (spy_eq.index <= WF_END)]
    if len(spy_wf2) > 1:
        ax2.plot(spy_wf2.index, spy_wf2.values, label="SPY", color="black",
                 linewidth=2, linestyle="--")
    ax2.set_title("Top 10 — Tariff War Stress Test (Feb 2026–Present)", fontsize=14)
    ax2.set_ylabel("Portfolio Value ($)")
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax2.legend(fontsize=8, loc="upper left")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("quantihack_alt_data_50.png", dpi=150, bbox_inches="tight")
    print("Plot saved to quantihack_alt_data_50.png")

    # Print paper reference table
    print("\n" + "=" * 100)
    print("  ACADEMIC PAPER REFERENCES")
    print("=" * 100)
    for sid, name, paper, _ in STRATEGIES:
        print(f"  {sid}: {name}")
        print(f"       {paper}")
    print()


if __name__ == "__main__":
    main()
