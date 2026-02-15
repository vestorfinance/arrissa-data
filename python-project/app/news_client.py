import requests
from datetime import datetime, timezone


ECONOMIC_CALENDAR_URL = "https://economic-calendar.tradingview.com/events"

# Supported currencies and their country mappings
SUPPORTED_CURRENCIES = ["USD", "CAD", "JPY", "EUR", "CHF", "AUD", "NZD", "GBP"]

CURRENCY_TO_COUNTRIES = {
    "USD": ["US"],
    "CAD": ["CA"],
    "JPY": ["JP"],
    "EUR": ["DE", "FR"],
    "CHF": ["CH"],
    "AUD": ["AU"],
    "NZD": ["NZ"],
    "GBP": ["GB"],
}


def currencies_to_countries(currencies: list) -> list:
    """Convert a list of currency codes to the country codes needed by the API."""
    countries = []
    for cur in currencies:
        countries.extend(CURRENCY_TO_COUNTRIES.get(cur.upper(), []))
    return list(dict.fromkeys(countries))  # deduplicate, preserve order


def fetch_economic_events(
    from_dt: datetime,
    to_dt: datetime,
    currencies: list = None,
    min_importance: int = 0,
) -> list | None:
    """
    Fetch economic events from TradingView economic calendar.
    from_dt / to_dt: UTC datetimes.
    currencies: list of currency codes, defaults to all supported.
    min_importance: 0 = medium+high, 1 = high only, -1 = all.
    Returns list of event dicts or None on failure.
    """
    if currencies is None:
        countries = currencies_to_countries(SUPPORTED_CURRENCIES)
    else:
        countries = currencies_to_countries(currencies)

    resp = requests.get(
        ECONOMIC_CALENDAR_URL,
        headers={"Origin": "https://in.tradingview.com"},
        params={
            "from": from_dt.isoformat(),
            "to": to_dt.isoformat(),
            "countries": ",".join(countries),
            "minImportance": min_importance,
        },
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json().get("result", [])
    return None
