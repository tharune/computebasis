"""Illustrative map placement for the simulated book's sites.

A site in the book is only an invented name such as "Demo Site 01-A (US)". The map needs a point, so each
site is assigned a well-known data-centre metro here. That assignment says nothing about where any real
seller operates: it is a stable, deterministic picture, labelled `illustrative_metro_assignment_not_vendor_location`.

* US sites take a contiguous-US metro by a stable hash of the site id. Metros are in distinct states, and a
  collision on the hash probes forward to the next unused state, so up to `len(US_METROS)` US sites never share
  a state. The result depends only on the set of US site ids, which a book never changes after it is built.
* Every other site sits at one fixed capital or main data-centre metro for its ISO country code (`state` is
  `None`). The table covers every country the population can produce and more; a code outside the table raises
  `UnknownCountryError` instead of inventing a point, because the ledger contract forbids a null position.
"""
from collections import namedtuple
import hashlib

Metro = namedtuple("Metro", "label state lat lon")

# Distinct states, so the first 24 US sites of a book are spread across 24 states. (label, state, latitude, longitude)
US_METROS = (
    Metro("Ashburn, VA", "VA", 39.0438, -77.4875),
    Metro("Dallas, TX", "TX", 32.7767, -96.7970),
    Metro("Phoenix, AZ", "AZ", 33.4484, -112.0740),
    Metro("Chicago, IL", "IL", 41.8781, -87.6298),
    Metro("Atlanta, GA", "GA", 33.7490, -84.3880),
    Metro("Columbus, OH", "OH", 39.9612, -82.9988),
    Metro("Hillsboro, OR", "OR", 45.5229, -122.9898),
    Metro("Quincy, WA", "WA", 47.2343, -119.8526),
    Metro("Salt Lake City, UT", "UT", 40.7608, -111.8910),
    Metro("Denver, CO", "CO", 39.7392, -104.9903),
    Metro("Las Vegas, NV", "NV", 36.1699, -115.1398),
    Metro("San Jose, CA", "CA", 37.3382, -121.8863),
    Metro("Omaha, NE", "NE", 41.2565, -95.9345),
    Metro("Kansas City, MO", "MO", 39.0997, -94.5786),
    Metro("Minneapolis, MN", "MN", 44.9778, -93.2650),
    Metro("Charlotte, NC", "NC", 35.2271, -80.8431),
    Metro("Miami, FL", "FL", 25.7617, -80.1918),
    Metro("Newark, NJ", "NJ", 40.7357, -74.1724),
    Metro("Boston, MA", "MA", 42.3601, -71.0589),
    Metro("Nashville, TN", "TN", 36.1627, -86.7816),
    Metro("Albuquerque, NM", "NM", 35.0844, -106.6504),
    Metro("Cheyenne, WY", "WY", 41.1400, -104.8202),
    Metro("Des Moines, IA", "IA", 41.5868, -93.6250),
    Metro("Oklahoma City, OK", "OK", 35.4676, -97.5164),
)

# Used only when a book has more US sites than there are distinct states above (no seed reaches this today).
US_OVERFLOW_METROS = (
    Metro("Los Angeles, CA", "CA", 34.0522, -118.2437),
    Metro("Houston, TX", "TX", 29.7604, -95.3698),
    Metro("Seattle, WA", "WA", 47.6062, -122.3321),
    Metro("Pittsburgh, PA", "PA", 40.4406, -79.9959),
    Metro("Detroit, MI", "MI", 42.3314, -83.0458),
    Metro("Boise, ID", "ID", 43.6150, -116.2023),
    Metro("Reno, NV", "NV", 39.5296, -119.8138),
    Metro("Richmond, VA", "VA", 37.5407, -77.4360),
)

# One fixed capital or main data-centre metro per non-US ISO 3166-1 alpha-2 code: (label, latitude, longitude).
COUNTRY_METROS = {
    "CA": ("Toronto", 43.6532, -79.3832),
    "DE": ("Frankfurt", 50.1109, 8.6821),
    "NL": ("Amsterdam", 52.3676, 4.9041),
    "JP": ("Tokyo", 35.6762, 139.6503),
    "SG": ("Singapore", 1.3521, 103.8198),
    "BR": ("São Paulo", -23.5505, -46.6333),
    "CL": ("Santiago", -33.4489, -70.6693),
    # Not produced by the population today; here so a wider book still has an honest, fixed point.
    "GB": ("London", 51.5074, -0.1278),
    "FR": ("Paris", 48.8566, 2.3522),
    "IE": ("Dublin", 53.3498, -6.2603),
    "SE": ("Stockholm", 59.3293, 18.0686),
    "FI": ("Helsinki", 60.1699, 24.9384),
    "NO": ("Oslo", 59.9139, 10.7522),
    "CH": ("Zurich", 47.3769, 8.5417),
    "ES": ("Madrid", 40.4168, -3.7038),
    "IT": ("Milan", 45.4642, 9.1900),
    "PL": ("Warsaw", 52.2297, 21.0122),
    "IN": ("Mumbai", 19.0760, 72.8777),
    "KR": ("Seoul", 37.5665, 126.9780),
    "AU": ("Sydney", -33.8688, 151.2093),
    "NZ": ("Auckland", -36.8509, 174.7645),
    "HK": ("Hong Kong", 22.3193, 114.1694),
    "TW": ("Taipei", 25.0330, 121.5654),
    "AE": ("Dubai", 25.2048, 55.2708),
    "ZA": ("Johannesburg", -26.2041, 28.0473),
    "MX": ("Mexico City", 19.4326, -99.1332),
    "AR": ("Buenos Aires", -34.6037, -58.3816),
    "CO": ("Bogotá", 4.7110, -74.0721),
    "IL": ("Tel Aviv", 32.0853, 34.7818),
    "ID": ("Jakarta", -6.2088, 106.8456),
    "MY": ("Kuala Lumpur", 3.1390, 101.6869),
}


class DeskLedgerError(ValueError):
    """The desk ledger cannot be built honestly from this book."""


class UnknownCountryError(DeskLedgerError):
    """A site's country has no fixed placement; add it to COUNTRY_METROS rather than guessing."""


def _digest(site_id):
    return int.from_bytes(hashlib.sha256(site_id.encode("utf-8")).digest()[:8], "big")


def _row(metro):
    return {"label": metro.label, "state": metro.state, "lat": metro.lat, "lon": metro.lon}


def assign_placements(sites):
    """Map `{site id: placement}` for `(site id, ISO country)` pairs; deterministic and independent of input order."""
    sites = dict(sites)
    result, used_states, used_metros = {}, set(), set()
    us_sites = sorted((site_id for site_id, country in sites.items() if country == "US"), key=lambda site_id: (_digest(site_id), site_id))
    for site_id in us_sites:
        start = _digest(site_id) % len(US_METROS)
        chosen = next((US_METROS[(start + step) % len(US_METROS)] for step in range(len(US_METROS))
                       if US_METROS[(start + step) % len(US_METROS)].state not in used_states), None)
        if chosen is None:
            chosen = next((metro for metro in US_OVERFLOW_METROS if metro not in used_metros), US_METROS[start])
        used_states.add(chosen.state)
        used_metros.add(chosen)
        result[site_id] = _row(chosen)
    for site_id, country in sorted(sites.items()):
        if country == "US":
            continue
        if country not in COUNTRY_METROS:
            raise UnknownCountryError(f"no placement for country {country!r}")
        label, lat, lon = COUNTRY_METROS[country]
        result[site_id] = {"label": label, "state": None, "lat": lat, "lon": lon}
    return result
