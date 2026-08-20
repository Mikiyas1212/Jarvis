"""
flight_finder.py — open Google Flights with origin, destination and an optional
date pre-filled, then speak a confirmation.

Params: origin, destination, date (optional; defaults to tomorrow).

Changes vs. the original:
  * The city→IATA table had duplicate "dubai" keys; de-duplicated.
  * Speaking now goes through assistant_io.say(), so the two different, partly
    broken event-loop code paths (one used get_event_loop().run_until_complete
    on a thread with no loop) are gone.
"""

import re
import webbrowser
from datetime import datetime, timedelta

from assistant_io import say


_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_CITY_TO_IATA = {
    "los angeles": "LAX", "new york": "JFK", "san francisco": "SFO",
    "chicago": "ORD", "miami": "MIA", "dallas": "DFW", "seattle": "SEA",
    "boston": "BOS", "atlanta": "ATL", "denver": "DEN", "las vegas": "LAS",
    "washington": "DCA", "houston": "IAH", "phoenix": "PHX", "london": "LHR",
    "paris": "CDG", "dubai": "DXB", "tokyo": "NRT", "toronto": "YYZ",
    "sydney": "SYD", "addis ababa": "ADD", "tbilisi": "TBS", "amsterdam": "AMS",
    "frankfurt": "FRA", "madrid": "MAD", "barcelona": "BCN", "rome": "FCO",
    "milan": "MXP",
}


def _normalise_date(date_str: str) -> str:
    """Natural-language date → YYYY-MM-DD, defaulting to tomorrow."""
    if not date_str:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    date_str = date_str.strip().lower()
    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
        return date_str[:10]

    m = re.search(r'([a-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?', date_str)
    if m and m.group(1) in _MONTHS:
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        return f"{year:04d}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"

    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _to_iata(location: str) -> str:
    clean = location.strip().lower()
    return _CITY_TO_IATA.get(clean, location.strip().upper())


def _build_flights_url(origin: str, destination: str, date_iso: str) -> str:
    org, dst = _to_iata(origin), _to_iata(destination)
    return (
        "https://www.google.com/travel/flights"
        f"?q=flights+from+{org}+to+{dst}+on+{date_iso}"
    )


def flight_finder(params: dict, player=None, speak=None) -> None:
    """Open Google Flights and speak a confirmation."""
    origin = params.get("origin", "").strip()
    destination = params.get("destination", "").strip()
    date_raw = params.get("date", "")

    if not origin or not destination:
        msg = "I need both an origin and a destination to find flights, sir."
        (speak or (lambda m: say(player, m)))(msg)
        return

    date_iso = _normalise_date(date_raw)
    webbrowser.open(_build_flights_url(origin, destination, date_iso))

    try:
        date_fmt = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%B %d")
    except Exception:
        date_fmt = date_iso

    msg = (f"Opening Google Flights for {origin} to {destination}"
           f"{' on ' + date_fmt if date_raw else ''}, sir.")

    if speak:
        speak(msg)
    else:
        say(player, msg)
