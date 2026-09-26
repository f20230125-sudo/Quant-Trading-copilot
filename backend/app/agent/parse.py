"""Plain-English request parsing for the local analyst.

Turns a message such as "backtest a 20/50 SMA crossover on vol 75 with a 1%
stop" into symbols, intents and a strategy spec. Rule-based on purpose: it
runs offline, costs nothing, and is fully testable. It only needs to cover the
questions this app is for; anything else gets a help message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# (symbol, pattern, case_sensitive). Case-sensitive patterns catch index names that
# are also everyday words ("step", "regime") only when written as the symbol.
_SYMBOL_PATTERNS: list[tuple[str, str, bool]] = [
    ("VOL100_1S", r"\b(?:vol(?:atility)?|v)\s*[-_ ]?100\s*[-_ ]?\(?\s*1\s*s(?:ec(?:ond)?)?\b\)?", False),
    ("VOL100", r"\b(?:vol(?:atility)?|v)\s*[-_ ]?100\b(?!\s*[-_ ]?\(?\s*1\s*s)(?!\s*%)", False),
    ("VOL10", r"\b(?:vol(?:atility)?|v)\s*[-_ ]?10\b(?!\s*%)", False),
    ("VOL25", r"\b(?:vol(?:atility)?|v)\s*[-_ ]?25\b(?!\s*%)", False),
    ("VOL50", r"\b(?:vol(?:atility)?|v)\s*[-_ ]?50\b(?!\s*%)", False),
    ("VOL75", r"\b(?:vol(?:atility)?|v)\s*[-_ ]?75\b(?!\s*%)", False),
    ("JUMP50", r"\bjump\s*[-_ ]?50\b|\bjump index\b", False),
    ("CRASH500", r"\bcrash\s*[-_ ]?500\b|\bcrash index\b", False),
    ("BOOM500", r"\bboom\s*[-_ ]?500\b|\bboom index\b", False),
    ("STEP", r"\bstep index\b", False),
    ("STEP", r"\bSTEP\b", True),
    ("REGIME", r"\bregime[- ]?(?:switch(?:ing)?[- ])?index\b", False),
    ("REGIME", r"\bREGIME\b", True),
    ("MOMENTUM50", r"\bmomentum\s*[-_ ]?50\b|\bmomentum index\b", False),
]

_ALL_SYMBOLS = re.compile(r"\b(all|every|each)\s+(the\s+)?(indices|indexes|index|markets|symbols)\b")

_INTENTS: dict[str, str] = {
    "compare": r"calmest|quietest|least volatile|most volatile|wildest|riskiest|\brank|\bcompare|comparison|"
    r"more volatile|less volatile|which (index|indices|one|market)s? (is|are) (the )?(most|least|more|less|calm|quiet|wild|risk)",
    "walk_forward": r"optimi[sz]|\btun(e|ing)\b|walk[- ]?forward|best param|parameter (search|sweep)|grid search|overfit",
    "backtest": r"back[- ]?test|\bstrateg|cross[- ]?over|moving average|\bsma\b|\bma\b|\brsi\b|breakout|donchian|"
    r"\bedge\b|profitab|trading rule|long[- ]only|short[- ]only|stop[- ]?loss|take[- ]?profit|\btry (a|an|it|the)\b",
    "regime": r"regime|turbulen|\bcalm\b|\bcalm or\b|state of the market",
    "volatility": r"volatil|\bvol\b|\bsigma\b|\bjump(s|ed)?\b|\bspike|how (risky|wild|calm|volatile)|garch|ewma|\brisk\b|big(gest)? moves?",
    "prices": r"\bprice|\bdoing\b|\bdone\b|\bmoved?\b|perform|summary|summari[sz]e|trend(ed|ing)?\b|last (hour|\d+ ?(min|minutes|hours?|h)\b)|chart",
    "list": r"\blist\b|what (indices|symbols|markets|can i)|which (indices|symbols|markets) (are|exist|can)|available|catalog",
}

_PREDICTION = re.compile(
    r"\bwill\s+(?:\w+\s+)?(go|rise|fall|drop|climb|move|crash|pump|dump)\b|going to (go|rise|fall|drop|move|crash)|"
    r"\bpredict|forecast (the |its )?(price|direction)|price target|should i (buy|sell|go long|short|enter)|"
    r"next (move|candle|tick|direction)|(up|down) (next|tomorrow|in the next)|which way"
)

_UNSUPPORTED = {
    "macd": ("MACD", "SMA crossover", "an SMA 12/26 crossover"),
    "bollinger": ("Bollinger Bands", "RSI mean-reversion", "RSI mean-reversion with 30/70 thresholds"),
    "ichimoku": ("Ichimoku", "SMA crossover", "an SMA 20/50 crossover"),
    "stochastic": ("the stochastic oscillator", "RSI mean-reversion", "RSI mean-reversion with 20/80 thresholds"),
    "vwap": ("VWAP", "SMA crossover", "an SMA 20/50 crossover"),
    "fibonacci": ("Fibonacci levels", "channel breakout", "a 50-tick breakout"),
    "machine learning": ("machine-learning signals", "SMA crossover", "an SMA 20/50 crossover"),
    "neural": ("neural-network signals", "SMA crossover", "an SMA 20/50 crossover"),
    "lstm": ("LSTM models", "SMA crossover", "an SMA 20/50 crossover"),
    "martingale": ("martingale position sizing", "fixed-size SMA crossover", "an SMA 20/50 crossover"),
}

_HELP = re.compile(r"^\s*(hi|hello|hey|yo|help|what can you do|how does this work|who are you|what are you)\b")


@dataclass
class Request:
    text: str
    symbols: list[str] = field(default_factory=list)
    all_symbols: bool = False
    intents: list[str] = field(default_factory=list)
    strategy: dict[str, Any] | None = None
    strategy_explicit: bool = False  # the message named a signal, not just modifiers
    granularity_s: int = 0
    count: int | None = None
    lookback_s: int | None = None
    prediction: bool = False
    unsupported: tuple[str, str, str] | None = None
    help: bool = False


def find_symbols(text: str) -> tuple[list[str], str]:
    """Symbols in order of mention, and the text with those mentions blanked out."""
    hits: list[tuple[int, int, str]] = []
    lower = text.lower()
    for symbol, pattern, case_sensitive in _SYMBOL_PATTERNS:
        for m in re.finditer(pattern, text if case_sensitive else lower):
            hits.append((m.start(), m.end(), symbol))
    hits.sort()
    symbols: list[str] = []
    stripped = list(lower)
    for start, end, symbol in hits:
        if symbol not in symbols:
            symbols.append(symbol)
        stripped[start:end] = " " * (end - start)
    return symbols, "".join(stripped)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_strategy(t: str) -> tuple[dict[str, Any], bool]:
    """Strategy spec from lower-cased text (symbols already removed). Returns (spec, named_a_signal)."""
    spec: dict[str, Any] = {}
    signal: dict[str, Any] | None = None

    if re.search(r"\brsi\b", t):
        period = re.search(r"rsi\s*\(?\s*(\d{1,3})\b|(\d{1,3})[- ]period rsi", t)
        bands = [(int(a), int(b)) for a, b in re.findall(r"\b(\d{1,2})\s*/\s*(\d{2})\b", t)]
        bands = [(lo, hi) for lo, hi in bands if 0 < lo < 50 < hi < 100]
        signal = {"type": "rsi", "mode": "momentum" if re.search(r"momentum|trend", t) else "mean_reversion"}
        if period:
            signal["period"] = int(period.group(1) or period.group(2))
        if bands:
            signal["lower"], signal["upper"] = bands[0]
    elif re.search(r"breakout|donchian|channel", t):
        lb = re.search(r"(\d{1,4})\s*[- ]?(?:tick|bar|period|candle)s?\b", t) or re.search(r"breakout\D{0,15}(\d{1,4})", t)
        signal = {"type": "breakout", "lookback": int(lb.group(1)) if lb else 50}
    elif re.search(r"\bsma\b|\bma\b|moving average|cross[- ]?over|\bcross\b", t):
        pair = (
            re.search(r"\b(\d{1,4})\s*[/x&]\s*(\d{1,4})\b", t)
            or re.search(r"\b(\d{1,4})\s*(?:and|vs\.?|,)\s*(\d{1,4})\b", t)
            or re.search(r"fast\D{0,8}(\d{1,4})\D{1,15}slow\D{0,8}(\d{1,4})", t)
        )
        if pair:
            fast, slow = sorted((int(pair.group(1)), int(pair.group(2))))
        elif re.search(r"\bfast|short[- ]term|quick|scalp", t):
            fast, slow = 2, 5
        elif re.search(r"\bslow|long[- ]term", t):
            fast, slow = 50, 200
        else:
            fast, slow = 20, 50
        signal = {"type": "sma_cross", "fast": fast, "slow": max(slow, fast + 1)}

    if signal:
        spec["signal"] = signal
    if re.search(r"long[- ]only|only long|longs only", t):
        spec["direction"] = "long_only"
    elif re.search(r"short[- ]only|only short|shorts only", t):
        spec["direction"] = "short_only"
    elif re.search(r"long[- ]short|both (ways|directions)", t):
        spec["direction"] = "long_short"

    stop = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:stop|sl\b)", t) or re.search(r"stop[- ]?(?:loss)?\D{0,10}?(\d+(?:\.\d+)?)\s*%", t)
    if stop:
        spec["stop_loss_pct"] = _num(stop.group(1))
    target = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:take[- ]?profit|target|tp\b)", t) or re.search(
        r"(?:take[- ]?profit|target|tp)\D{0,10}?(\d+(?:\.\d+)?)\s*%", t
    )
    if target:
        spec["take_profit_pct"] = _num(target.group(1))
    if re.search(r"\b(zero|no|without|0)\s+(fees?|costs?|commissions?)|\bfee[- ]?free|\bfrictionless", t):
        spec["fee_bps"] = 0.0
    else:
        fee = re.search(r"(\d+(?:\.\d+)?)\s*(?:bp|bps|basis points?)\b", t)
        if fee:
            spec["fee_bps"] = _num(fee.group(1))
    return spec, signal is not None


def parse(text: str) -> Request:
    symbols, t = find_symbols(text)
    req = Request(text=text, symbols=symbols, all_symbols=bool(_ALL_SYMBOLS.search(t)))

    unsupported = next((v for k, v in _UNSUPPORTED.items() if re.search(rf"\b{k}", t)), None)
    req.unsupported = unsupported
    req.prediction = bool(_PREDICTION.search(t))

    for name, pattern in _INTENTS.items():
        if re.search(pattern, t):
            req.intents.append(name)
    # "list" only when nothing more specific was asked; "prices" likewise yields to analyses.
    if "list" in req.intents and len(req.intents) > 1:
        req.intents.remove("list")
    if "prices" in req.intents and any(i in req.intents for i in ("volatility", "regime", "backtest", "walk_forward", "compare")):
        req.intents.remove("prices")
    if "walk_forward" in req.intents and "backtest" in req.intents and not re.search(r"back[- ]?test", t):
        req.intents.remove("backtest")
    if "compare" in req.intents and len(symbols) == 1:
        # "VOL75 compared with its design" is about one index, not a ranking.
        req.intents.remove("compare")
        if "volatility" not in req.intents:
            req.intents.append("volatility")
    if "compare" in req.intents and "volatility" in req.intents:
        req.intents.remove("volatility")

    req.strategy, req.strategy_explicit = parse_strategy(t)
    # "compare a fast SMA crossover on X and Y" compares backtests, not volatility.
    if req.strategy_explicit and "compare" in req.intents and ("backtest" in req.intents or "walk_forward" in req.intents):
        req.intents.remove("compare")

    candles = re.search(r"(\d+)\s*[- ]?(min(?:ute)?s?|m|h(?:our)?s?)\b\s*[- ]?(?:candles?|bars?)", t)
    if candles:
        req.granularity_s = int(candles.group(1)) * (3600 if candles.group(2).startswith("h") else 60)
    elif re.search(r"minute (candles|bars)", t):
        req.granularity_s = 60
    elif re.search(r"hourly (candles|bars)", t):
        req.granularity_s = 3600

    count = re.search(r"(?:last|over|using)\s+(\d[\d,]*)\s*(?:ticks|bars|candles|points)", t)
    if count:
        req.count = int(_num(count.group(1)))
    span = re.search(r"(?:last|past|over the)\s+(\d+)?\s*(hour|hr|h|minute|min|day)s?\b", t)
    if span:
        n = int(span.group(1) or 1)
        req.lookback_s = n * {"hour": 3600, "hr": 3600, "h": 3600, "minute": 60, "min": 60, "day": 86400}[span.group(2)]

    req.help = bool(_HELP.search(t)) and not req.intents
    return req
