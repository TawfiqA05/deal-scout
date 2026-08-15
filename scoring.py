"""
Deal Scout scoring engine.
Takes the asking price + comparable eBay listings and answers:
BUY, NEGOTIATE, or PASS — with an honest profit range.

Every estimate here is based on ACTIVE listings (what sellers are asking),
not confirmed sales. Real sale prices are usually lower. Estimates are
therefore optimistic and labeled as such everywhere they appear.
"""

import statistics
import settings


def pick_fee_percent(category_guess: str | None) -> float:
    """Match the guessed category to an eBay fee, or use the default."""
    if category_guess:
        guess = category_guess.lower()
        for name, fee in settings.EBAY_CATEGORY_FEES.items():
            if name != "default" and name in guess:
                return fee
    return settings.EBAY_CATEGORY_FEES["default"]


def summarize_comps(comp_prices: list[float]) -> dict:
    """Turn a pile of comparable listing prices into a resale range.
    Trims the extreme cheap/expensive outliers first."""
    if not comp_prices:
        return {"count": 0, "low": None, "high": None, "median": None}

    prices = sorted(comp_prices)
    trim = int(len(prices) * settings.COMPS_TRIM_PERCENT / 100)
    if trim and len(prices) > 2 * trim:
        prices = prices[trim:-trim]

    median = statistics.median(prices)
    # Resale range: conservative = 25th percentile-ish, optimistic = median.
    # (Active-listing medians already run high vs. real sold prices.)
    low = prices[max(0, len(prices) // 4 - 1)] if len(prices) >= 4 else prices[0]
    return {
        "count": len(comp_prices),
        "low": round(low, 2),
        "high": round(median, 2),
        "median": round(median, 2),
    }


def score_deal(asking_price: float,
               comp_prices: list[float],
               category_guess: str | None,
               size_class: str) -> dict:
    """The verdict. Returns everything the results page needs."""
    fee_pct = pick_fee_percent(category_guess)
    shipping = settings.SHIPPING_ESTIMATES.get(size_class,
                                               settings.SHIPPING_ESTIMATES["medium"])
    comps = summarize_comps(comp_prices)

    if comps["count"] == 0:
        return {
            "verdict": "PASS",
            "reason": ("No comparable listings found — can't estimate resale "
                       "value, so there's no basis for a buy decision."),
            "fee_percent": fee_pct, "shipping_est": shipping,
            "comps": comps, "est_profit_low": None, "est_profit_high": None,
            "suggested_offer": None,
        }

    def profit_at(purchase_price: float, resale: float) -> float:
        fees = resale * fee_pct / 100 + settings.EBAY_PER_ORDER_FEE
        return resale - fees - shipping - purchase_price

    profit_low = round(profit_at(asking_price, comps["low"]), 2)
    profit_high = round(profit_at(asking_price, comps["high"]), 2)

    def meets_bar(purchase_price: float) -> bool:
        """BUY bar uses the CONSERVATIVE resale estimate, not the optimistic one."""
        p = profit_at(purchase_price, comps["low"])
        return (p >= settings.MIN_PROFIT_DOLLARS and
                purchase_price > 0 and
                (p / purchase_price) * 100 >= settings.MIN_PROFIT_PERCENT)

    if meets_bar(asking_price):
        verdict, reason, suggested_offer = "BUY", (
            f"Even at the conservative resale estimate (${comps['low']:.2f}), "
            f"this clears your ${settings.MIN_PROFIT_DOLLARS}/"
            f"{settings.MIN_PROFIT_PERCENT}% profit bar at full asking price."
        ), None
    else:
        # Would it become a BUY at a realistic discount?
        floor = asking_price * (1 - settings.NEGOTIATE_DISCOUNT_LIMIT / 100)
        target = None
        price = asking_price
        while price >= floor:
            price = round(price - max(1, asking_price * 0.02), 2)
            if meets_bar(price):
                target = price
                break
        if target:
            verdict = "NEGOTIATE"
            suggested_offer = round(target * 0.95, 0)  # open a bit under target
            reason = (
                f"Doesn't clear your profit bar at ${asking_price:.2f}, but does "
                f"at ${target:.2f} — that's within a realistic negotiation range. "
                f"Suggested opening offer: ${suggested_offer:.0f}."
            )
        else:
            verdict, suggested_offer = "PASS", None
            reason = (
                f"Even at {settings.NEGOTIATE_DISCOUNT_LIMIT}% below asking, this "
                f"doesn't clear your ${settings.MIN_PROFIT_DOLLARS}/"
                f"{settings.MIN_PROFIT_PERCENT}% profit bar using the conservative "
                f"resale estimate. Not worth your time."
            )

    return {
        "verdict": verdict,
        "reason": reason,
        "fee_percent": fee_pct,
        "shipping_est": shipping,
        "comps": comps,
        "est_profit_low": profit_low,
        "est_profit_high": profit_high,
        "suggested_offer": suggested_offer,
    }
