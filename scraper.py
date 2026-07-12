#!/usr/bin/env python3
"""
London Property Dashboard — OnTheMarket Live Scraper
=====================================================
Scrapes OnTheMarket for-sale listings across London & commuter-belt areas,
estimates rental income from OnTheMarket to-rent listings in the same areas,
and writes live_listings.json for the dashboard.

Usage:
    python scraper.py

Output: live_listings.json  (same folder as index.html)
Takes approx 5-15 minutes with polite delays between requests.
"""

import json
import re
import time
import random
import datetime
import sys
import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
OUTPUT_FILE   = Path(__file__).parent / 'live_listings.json'
PRICE_MIN     = 300_000
PRICE_MAX     = 800_000
MIN_BEDS      = 2          # 2+ beds only; 3-bed needs 2+ baths, 4-bed needs 3+ baths, etc.
MAX_PER_AREA  = 20         # listings per area (OTM returns ~30 per page; 20×41 areas ≈ 800 max)
REQUEST_DELAY = (3, 6)     # polite pause between requests (seconds)

# ── SEARCH AREAS ──────────────────────────────────────────────────────────────
# OTM uses postcode outcodes directly in the URL path
SEARCH_AREAS = [
    {'name': 'Hackney',       'postcode': 'e8',   'search_area': 'East London'},
    {'name': 'Stratford',     'postcode': 'e15',  'search_area': 'East London'},
    {'name': 'Bethnal Green', 'postcode': 'e2',   'search_area': 'East London'},
    {'name': 'Leyton',        'postcode': 'e10',  'search_area': 'East London'},
    {'name': 'East Ham',      'postcode': 'e6',   'search_area': 'East London'},
    {'name': 'Canning Town',  'postcode': 'e16',  'search_area': 'East London'},
    {'name': 'Lewisham',      'postcode': 'se13', 'search_area': 'South London'},
    {'name': 'Peckham',       'postcode': 'se15', 'search_area': 'South London'},
    {'name': 'Greenwich',     'postcode': 'se10', 'search_area': 'South London'},
    {'name': 'Woolwich',      'postcode': 'se18', 'search_area': 'South London'},
    {'name': 'Croydon',       'postcode': 'cr0',  'search_area': 'South London'},
    {'name': 'Bromley',       'postcode': 'br1',  'search_area': 'South London'},
    {'name': 'Catford',       'postcode': 'se6',  'search_area': 'South London'},
    {'name': 'Abbey Wood',    'postcode': 'se2',  'search_area': 'South London'},
    {'name': 'Clapham',       'postcode': 'sw4',  'search_area': 'South West London'},
    {'name': 'Wimbledon',     'postcode': 'sw19', 'search_area': 'South West London'},
    {'name': 'Balham',        'postcode': 'sw12', 'search_area': 'South West London'},
    {'name': 'Tooting',       'postcode': 'sw17', 'search_area': 'South West London'},
    {'name': 'Streatham',     'postcode': 'sw16', 'search_area': 'South West London'},
    {'name': 'Battersea',     'postcode': 'sw11', 'search_area': 'South West London'},
    {'name': 'Earlsfield',    'postcode': 'sw18', 'search_area': 'South West London'},
    {'name': 'Kingston',      'postcode': 'kt1',  'search_area': 'South West London'},
    {'name': 'Sutton',        'postcode': 'sm1',  'search_area': 'South West London'},
    {'name': 'Walthamstow',   'postcode': 'e17',  'search_area': 'North London'},
    {'name': 'Tottenham',     'postcode': 'n17',  'search_area': 'North London'},
    {'name': 'Enfield',       'postcode': 'en1',  'search_area': 'North London'},
    {'name': 'Wood Green',    'postcode': 'n22',  'search_area': 'North London'},
    {'name': 'Wembley',       'postcode': 'ha9',  'search_area': 'West London'},
    {'name': 'Harrow',        'postcode': 'ha1',  'search_area': 'West London'},
    {'name': 'Hounslow',      'postcode': 'tw3',  'search_area': 'West London'},
    {'name': 'Ilford',        'postcode': 'ig1',  'search_area': 'Outer London'},
    {'name': 'Barking',       'postcode': 'ig11', 'search_area': 'Outer London'},
    {'name': 'Romford',       'postcode': 'rm1',  'search_area': 'Outer London'},
    {'name': 'Dagenham',      'postcode': 'rm10', 'search_area': 'Outer London'},
    {'name': 'Dartford',      'postcode': 'da1',  'search_area': 'Outer London'},
    {'name': 'Watford',       'postcode': 'wd17', 'search_area': 'Commuter Belt'},
    {'name': 'Reading',       'postcode': 'rg1',  'search_area': 'Commuter Belt'},
    {'name': 'Slough',        'postcode': 'sl1',  'search_area': 'Commuter Belt'},
    {'name': 'Luton',         'postcode': 'lu1',  'search_area': 'Commuter Belt'},
    {'name': 'Chelmsford',    'postcode': 'cm1',  'search_area': 'Commuter Belt'},
    {'name': 'Basildon',      'postcode': 'ss14', 'search_area': 'Commuter Belt'},
]

# Fallback rent estimates (£/mo) used when OTM to-rent scrape finds nothing
RENT_FALLBACKS = {
    'East London':   {1: 1800, 2: 2100, 3: 2650},
    'South London':  {1: 1700, 2: 1950, 3: 2500},
    'South West London': {1: 1850, 2: 2300, 3: 3000},
    'West London':   {1: 1500, 2: 1800, 3: 2250},
    'North London':  {1: 1800, 2: 2050, 3: 2600},
    'Outer London':  {1: 1500, 2: 1700, 3: 2100},
    'Commuter Belt': {1: 1350, 2: 1600, 3: 2000},
}

# ── HTTP SESSION ──────────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-GB,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.onthemarket.com/',
})


def get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=25)
            if r.status_code == 429:
                wait = 30 + attempt * 20
                log.warning(f'Rate limited — waiting {wait}s')
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == retries - 1:
                log.warning(f'  Request failed: {e}')
                return None
            time.sleep(random.uniform(5, 10))
    return None


def sleep():
    time.sleep(random.uniform(*REQUEST_DELAY))


# ── OTM PAGE PARSER ───────────────────────────────────────────────────────────
def extract_otm_listings(html: str) -> list[dict]:
    """
    OnTheMarket embeds all listing data in a __NEXT_DATA__ JSON block.
    This is very reliable — no CSS selector fragility.
    """
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>',
        html, re.DOTALL
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    # Navigate to listings inside the Redux state
    redux = data.get('props', {}).get('initialReduxState', {})
    results = redux.get('results', {})

    # Try multiple known paths where OTM stores listings
    listings = (
        results.get('hits', [])
        or results.get('listings', [])
        or results.get('properties', [])
        or _deep_find_listings(redux)
    )
    return listings


def _deep_find_listings(obj, depth=0):
    """Recursively search for the listings array inside the JSON."""
    if depth > 6:
        return []
    if isinstance(obj, list) and len(obj) > 0:
        first = obj[0]
        if isinstance(first, dict) and 'price' in first and 'id' in first:
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _deep_find_listings(v, depth + 1)
            if result:
                return result
    return []


# ── PARSE A SINGLE LISTING ────────────────────────────────────────────────────
def parse_listing(p: dict, area: dict) -> dict | None:
    """Convert a raw OTM listing dict into our dashboard format."""
    try:
        # Price
        price_raw = p.get('price', '')
        price = int(re.sub(r'[^\d]', '', str(price_raw)))
        if not PRICE_MIN <= price <= PRICE_MAX:
            return None

        prop_id   = str(p.get('id', ''))
        beds      = int(p.get('bedrooms') or 0)
        baths     = int(p.get('bathrooms') or 1)

        # Bedroom/bathroom rules: 2+ beds only; 3-bed needs 2+ baths, 4-bed 3+ baths...
        if beds < MIN_BEDS:
            return None
        if beds >= 3 and baths < beds - 1:
            return None
        address   = p.get('address', area['name'])
        prop_type = _normalise_type(p.get('humanised-property-type', ''))
        detail_url = p.get('details-url', '')
        full_url  = f'https://www.onthemarket.com{detail_url}' if detail_url else ''
        title     = p.get('property-title', f'{beds} bed {prop_type} in {area["name"]}')

        # Image
        cover = p.get('cover-image', {}) or {}
        image = cover.get('default', '')

        # Features list — OTM often includes tenure here
        features = p.get('features', []) or []
        tenure, lease_years = _parse_tenure(features)

        # Floor area from features
        size_m2 = _parse_size(features)

        # Service charge from features
        est_levy = _parse_service_charge(features)

        return {
            'prop_id':    prop_id,
            'title':      title[:120],
            'address':    address,
            'price':      price,
            'beds':       beds,
            'baths':      baths,
            'type':       prop_type,
            'url':        full_url,
            'image':      image,
            'tenure':     tenure,
            'lease_years': lease_years,
            'size_m2':    size_m2,
            'est_levy':   est_levy,
        }
    except Exception as e:
        log.debug(f'  Parse error: {e}')
        return None


def _normalise_type(t: str) -> str:
    t = (t or '').lower()
    if any(k in t for k in ('flat', 'apartment', 'maisonette', 'studio')):
        return 'Apartment'
    if 'terraced' in t:
        return 'Terraced'
    if 'semi' in t:
        return 'Semi-detached'
    if 'detached' in t:
        return 'Detached'
    return 'House'


def _parse_tenure(features: list) -> tuple:
    """Extract tenure and lease years from OTM features list."""
    for f in features:
        f = str(f)
        if re.search(r'\bfreehold\b', f, re.I):
            return 'Freehold', None
        if re.search(r'\bleasehold\b', f, re.I):
            m = re.search(r'(\d{2,4})\s*(?:years?|yrs?)', f, re.I)
            yrs = int(m.group(1)) if m and 10 < int(m.group(1)) < 999 else None
            return 'Leasehold', yrs
    return None, None


def _parse_size(features: list) -> int | None:
    """Extract floor area in m² from features."""
    for f in features:
        f = str(f)
        m = re.search(r'(\d{2,4})\s*(?:sq\.?\s*m|m²|m2)\b', f, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r'(\d{3,5})\s*(?:sq\.?\s*ft|sqft|ft²)\b', f, re.I)
        if m:
            return round(int(m.group(1)) * 0.0929)
    return None


def _parse_service_charge(features: list) -> int | None:
    """Extract monthly service charge from features."""
    for f in features:
        f = str(f)
        m = re.search(r'service\s+charge[^£\d]{0,20}£\s*([\d,]+)', f, re.I)
        if not m:
            m = re.search(r'£\s*([\d,]+)\s*(?:pa|p\.a\.|per\s+annum)[^.]{0,30}service', f, re.I)
        if m:
            annual = int(m.group(1).replace(',', ''))
            if 100 < annual < 30_000:
                return round(annual / 12)
    return None


# ── FOR-SALE SEARCH ───────────────────────────────────────────────────────────
def search_for_sale(postcode: str, max_results: int = MAX_PER_AREA) -> list[dict]:
    url = f'https://www.onthemarket.com/for-sale/property/{postcode}/'
    r = get(url, params={'min-price': PRICE_MIN, 'max-price': PRICE_MAX, 'min-bedrooms': MIN_BEDS})
    if not r:
        return []
    listings = extract_otm_listings(r.text)
    if not listings:
        log.warning('  Could not extract listings from page')
    return listings  # cap applied after bed/bath filtering in main()


# ── RENTAL ESTIMATE ───────────────────────────────────────────────────────────
def get_area_rents(postcode: str, search_area: str) -> dict:
    """Fetch to-rent listings to estimate average monthly rent by bed count."""
    url = f'https://www.onthemarket.com/to-rent/property/{postcode}/'
    r = get(url)
    fallback = RENT_FALLBACKS.get(search_area, {1: 1600, 2: 1900, 3: 2400})
    if not r:
        return fallback

    listings = extract_otm_listings(r.text)
    bucket: dict[int, list[int]] = {}

    for p in listings:
        try:
            beds = int(p.get('bedrooms') or 0)
            price_raw = str(p.get('price', ''))
            amount = int(re.sub(r'[^\d]', '', price_raw))
            # OTM to-rent prices are monthly
            if 200 < amount < 10_000:
                bucket.setdefault(beds, []).append(amount)
        except Exception:
            pass

    avgs: dict[int, int] = {}
    for beds, rents in bucket.items():
        if rents:
            avgs[beds] = round(sum(rents) / len(rents) / 50) * 50

    for b in (1, 2, 3):
        if b not in avgs:
            avgs[b] = fallback.get(b, 1600)

    return avgs


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    log.info('London Property Dashboard — OnTheMarket scraper starting')
    log.info(f'Price range: £{PRICE_MIN:,} – £{PRICE_MAX:,} | Max {MAX_PER_AREA} per area\n')

    # Carry first_seen dates over from the previous scrape so "new" detection works
    prev_first_seen: dict = {}
    if OUTPUT_FILE.exists():
        try:
            old = json.loads(OUTPUT_FILE.read_text(encoding='utf-8'))
            prev_first_seen = {l['id']: l.get('first_seen') for l in old.get('listings', [])}
        except Exception:
            pass
    now_iso = datetime.datetime.utcnow().isoformat()

    all_listings: list[dict] = []
    counter = 1

    for area in SEARCH_AREAS:
        log.info(f"[{area['postcode'].upper()}] {area['name']}  ({area['search_area']})")

        # 1. Rental estimates
        sleep()
        rents = get_area_rents(area['postcode'], area['search_area'])
        log.info(f'  Rent estimates: {rents}')

        # 2. For-sale listings
        sleep()
        raw = search_for_sale(area['postcode'])
        if not raw:
            log.warning(f'  No listings found — skipping')
            continue
        log.info(f'  {len(raw)} listing(s) found')

        area_count = 0
        for p in raw:
            if area_count >= MAX_PER_AREA:
                break
            parsed = parse_listing(p, area)
            if not parsed:
                continue
            area_count += 1

            beds = parsed['beds'] or 2
            est_rent = rents.get(beds) or rents.get(2, 1600)

            # Default tenure by property type if OTM didn't include it
            tenure = parsed['tenure']
            lease_years = parsed['lease_years']
            if not tenure:
                if parsed['type'] in ('Detached', 'Semi-detached', 'Terraced'):
                    tenure = 'Freehold'
                else:
                    tenure = 'Leasehold'

            lid = f"OTM{parsed['prop_id'] or str(counter)}"   # stable across scrapes
            listing = {
                'id':          lid,
                'first_seen':  prev_first_seen.get(lid) or now_iso,
                'title':       parsed['title'],
                'suburb':      area['name'],
                'postcode':    area['postcode'].upper(),
                'url':         parsed['url'],
                'price':       parsed['price'],
                'beds':        str(beds),
                'baths':       str(parsed['baths']),
                'size_m2':     parsed['size_m2'],
                'type':        parsed['type'],
                'image':       parsed['image'],
                'search_area': area['search_area'],
                'tenure':      tenure,
                'lease_years': lease_years,
                'dcf': {
                    'est_monthly_rent': est_rent,
                    'est_levy':         parsed['est_levy'] or 200,
                },
            }

            log.info(
                f'  → #{counter} {parsed["address"][:45]} | '
                f'£{parsed["price"]:,} | {beds}bed | '
                f'{tenure}{" "+str(lease_years)+"yr" if lease_years else ""} | '
                f'rent est £{est_rent}/mo'
            )
            all_listings.append(listing)
            counter += 1

    if not all_listings:
        log.error('\nNo listings scraped. Check your internet connection and try again.')
        sys.exit(1)

    output = {
        'scraped_at':  datetime.datetime.utcnow().isoformat(),
        'total_found': len(all_listings),
        'price_min':   min(p['price'] for p in all_listings),
        'price_max':   max(p['price'] for p in all_listings),
        'listings':    all_listings,
        'assumptions': {
            'mortgage_rate':   5.0,
            'deposit_pct':     25.0,
            'loan_term_yrs':   25,
            'cap_growth_pct':  5.0,
            'rent_growth_pct': 4.0,
            'vacancy_pct':     5.0,
            'agent_fee_pct':   12.0,
            'maint_pct':       1.0,
            'hold_years':      7,
            'exit_fee_pct':    2.0,
        },
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    log.info(f'\n✓  Saved {len(all_listings)} listings → {OUTPUT_FILE}')
    log.info('   Start the server (python -m http.server 3939) then open http://localhost:3939')


if __name__ == '__main__':
    main()
