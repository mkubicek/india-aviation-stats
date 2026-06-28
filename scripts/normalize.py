"""Fetch DGCA Excel workbooks and normalize them into aggregated CSVs.

Downloads DGCA portal/S3 workbooks (domestic monthly + international quarterly
traffic) and writes tidy aggregate CSVs under data/raw/aviation/aggregated/ for
the clean stage.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import warnings
from dataclasses import dataclass
from datetime import date
from email.utils import formatdate, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
AVIATION_RAW_DIR = RAW_DIR / "aviation"
DGCA_RAW_DIR = AVIATION_RAW_DIR / "dgca"
AGGREGATED_DIR = AVIATION_RAW_DIR / "aggregated"
_TIMED_OUT = False
_TIMEOUT_STARTED_AT: float | None = None

DGCA_SCAN_URL = "https://www.dgca.gov.in/digigov-portal/scan?"
DGCA_S3_BASE = "https://public-prd-dgca.s3.ap-south-1.amazonaws.com"
DGCA_DOMESTIC_PATH = (
    "InventoryList/dataReports/aviationDataStatistics/airTransport/domestic/monthly"
)
DGCA_INTERNATIONAL_PATH = (
    "InventoryList/dataReports/aviationDataStatistics/airTransport/international/quaterly"
)
DGCA_PARENT_CONTENT_ID = "4184"
DGCA_RULE_BOOK_ID = "259"

REQUEST_DATA = {
    "baseLocale": "",
    "screenId": "10000001",
    "classification": "",
    "actionVal": "viewStaticData",
    "requestType": "ApplicationRH",
    "attachId": "",
    "langType": "2",
    "ruleBookId": DGCA_RULE_BOOK_ID,
    "attr": "",
}

MONTH_MAP = {
    "JAN": "01",
    "JANUARY": "01",
    "FEB": "02",
    "FEBRUARY": "02",
    "FEBURUARY": "02",
    "MAR": "03",
    "MARCH": "03",
    "APR": "04",
    "APRIL": "04",
    "MAY": "05",
    "JUN": "06",
    "JUNE": "06",
    "JUL": "07",
    "JULY": "07",
    "AUG": "08",
    "AUGUST": "08",
    "SEP": "09",
    "SEPT": "09",
    "SEPTEMBER": "09",
    "OCT": "10",
    "OCTOBER": "10",
    "NOV": "11",
    "NOVEMBER": "11",
    "DEC": "12",
    "DECEMBER": "12",
}

AIRLINE_MAP = {
    "air asia": "AirAsia India",
    "air asia india": "AirAsia India",
    "air deccan": "Air Deccan",
    "air heritage": "Air Heritage",
    "air india": "Air India",
    "air india express": "Air India Express",
    "air taxi": "Air Taxi",
    "airasia": "AirAsia India",
    "aircarnival": "Air Carnival",
    "aircosta": "Air Costa",
    "airindia": "Air India",
    "airindiaexpress": "Air India Express",
    "airodisha": "Air Odisha",
    "airpegasus": "Air Pegasus",
    "aix connect": "AIX Connect",
    "akasa air": "Akasa Air",
    "alliance": "Alliance Air",
    "alliance air": "Alliance Air",
    "bluedart": "Blue Dart Aviation",
    "deccanair": "Air Deccan",
    "fly": "Fly91",
    "flybig": "Flybig",
    "go air": "Go First",
    "goair": "Go First",
    "india one air": "India One Air",
    "indigo": "IndiGo",
    "jetairways": "Jet Airways",
    "jetlite": "JetLite",
    "pawan hans": "Pawan Hans",
    "pawanhans": "Pawan Hans",
    "quikjetcargo": "QuikJet Cargo",
    "spicejet": "SpiceJet",
    "star air": "Star Air",
    "starair": "Star Air",
    "totaldom": "Total Domestic",
    "totalint": "Total International",
    "trujet": "TruJet",
    "truejet": "TruJet",
    "vistara": "Vistara",
    "zoomair": "Zoom Air",
}

DOMESTIC_CARRIER_COLUMNS = [
    "Type",
    "Airline",
    "Year",
    "Month",
    "Aircraft Number",
    "Aircraft Hours",
    "Aircraft Kilometres",
    "Passenger Number",
    "Passenger Kilometers",
    "Seat Kilometers",
    "Passenger Load Factor",
    "Freight",
    "Mail",
    "Total Cargo",
    "Passenger Tonne Kilometer",
    "Mail Tonne Kilometer",
    "Freight Tonne Kilometer",
    "Total Tonne Kilometer",
    "Available Tonne Kilometer",
    "Weight Load Factor",
]

@dataclass(frozen=True)
class DownloadStats:
    attempted: int = 0
    downloaded: int = 0
    cached: int = 0
    missing: int = 0
    failed: int = 0

    def add(self, status: str) -> "DownloadStats":
        values = self.__dict__.copy()
        values["attempted"] += 1
        values[status] += 1
        return DownloadStats(**values)


class DataUrlExtractor(HTMLParser):
    """Extract DGCA portal ``data-url`` attributes without a browser."""

    def __init__(self) -> None:
        super().__init__()
        self.data_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "data-url" and value:
                self.data_urls.append(value)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "india-aviation-stats/1.0 "
                "(direct-source open data ingestion; contact via GitHub)"
            )
        }
    )
    return session


def _download_timeout() -> int:
    return int(os.environ.get("DOWNLOAD_TIMEOUT", "0"))


def _sleep_seconds() -> float:
    return float(os.environ.get("DGCA_DISCOVERY_SLEEP", "0.5"))


def _time_remaining(started: float) -> bool:
    global _TIMED_OUT
    timeout = _download_timeout()
    if timeout <= 0:
        return True
    effective_started = _TIMEOUT_STARTED_AT if _TIMEOUT_STARTED_AT is not None else started
    if (time.monotonic() - effective_started) < timeout:
        return True
    _TIMED_OUT = True
    return False


def was_timed_out() -> bool:
    """Return whether this ingestion run hit the soft download timeout."""
    return _TIMED_OUT


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _clean_key(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]+", " ", _clean_text(value).upper()).strip()
    return text.replace("PASSENEGER", "PASSENGER")


def _to_number(value: object) -> float | int | None:
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return value
    text = _clean_text(value).replace(",", "")
    if text in {"", "-"}:
        return 0
    try:
        return float(text)
    except ValueError:
        return None


def _month_number(value: object) -> str | None:
    key = _clean_key(value).replace("*", "")
    return MONTH_MAP.get(key)


def _normalize_airline(name: str) -> str:
    key = re.sub(r"\d+", "", name).replace("%20", " ")
    key = re.sub(r"[_-]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip().lower()
    return AIRLINE_MAP.get(key, key.title())


def _source_year_from_filename(path: Path) -> int | None:
    match = re.search(r"(\d{2})(?!.*\d)", path.stem)
    if not match:
        return None
    return 2000 + int(match.group(1))


def _date_from_domestic_city_filename(path: Path) -> tuple[int, str] | None:
    stem = unquote(path.stem).replace("%20", " ")
    stem = re.sub(r"\bAPR\s+IL\b", "APRIL", stem, flags=re.IGNORECASE)
    month_pattern = "|".join(sorted(MONTH_MAP, key=len, reverse=True))
    match = re.search(rf"\b({month_pattern})\b\s*,?\s*(20\d{{2}})", stem, re.IGNORECASE)
    if not match:
        return None
    month = MONTH_MAP[_clean_key(match.group(1))]
    return int(match.group(2)), month


def _read_excel(path: Path) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_excel(path, header=None)


def _read_excel_sheets(path: Path) -> list[pd.DataFrame]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sheets = pd.read_excel(path, header=None, sheet_name=None)
    return list(sheets.values())


def _find_header_row(df: pd.DataFrame, required_terms: list[str]) -> int | None:
    required = [term.upper() for term in required_terms]
    for idx, row in df.iterrows():
        text = " ".join(_clean_key(value) for value in row.tolist())
        if all(term in text for term in required):
            return int(idx)
    return None


def _find_col(header: pd.Series, *terms: str) -> int | None:
    normalized_terms = [term.upper() for term in terms]
    for col, value in header.items():
        text = _clean_key(value)
        if all(term in text for term in normalized_terms):
            return int(col)
    return None


def _iter_html_strings(content: str) -> list[str]:
    strings = [content]
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return strings

    def visit(obj: object) -> None:
        if isinstance(obj, dict):
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            for item in obj:
                visit(item)
        elif isinstance(obj, str):
            if "<a" in obj.lower() or "data-url" in obj.lower() or "<table" in obj.lower():
                strings.append(obj)
            elif obj.strip().startswith(("{", "[")):
                try:
                    visit(json.loads(obj))
                except (json.JSONDecodeError, ValueError):
                    pass

    visit(data)
    return strings


def _extract_data_urls(content: str) -> list[str]:
    urls: list[str] = []
    for html_content in _iter_html_strings(content):
        parser = DataUrlExtractor()
        parser.feed(html_content)
        urls.extend(parser.data_urls)
        urls.extend(re.findall(r"jsp[/a-zA-Z0-9 _%,.()-]+", html_content))
    return sorted(set(html.unescape(url).strip() for url in urls if url.strip()))


def _normalize_dgca_url(raw_url: str) -> str | None:
    raw_url = html.unescape(raw_url).strip()
    if not raw_url:
        return None
    if raw_url.startswith("http"):
        return raw_url
    if raw_url.startswith("jsp/dgca"):
        return raw_url.replace("jsp/dgca", DGCA_S3_BASE, 1)
    if raw_url.startswith("InventoryList/"):
        return f"{DGCA_S3_BASE}/{raw_url}"
    return None


def _extract_excel_urls(content: str) -> set[str]:
    urls: set[str] = set()
    for raw_url in _extract_data_urls(content):
        normalized = _normalize_dgca_url(raw_url)
        if normalized and normalized.lower().endswith((".xls", ".xlsx")):
            urls.add(normalized)
    return urls


def _extract_html_content_ids(content: str) -> set[str]:
    ids: set[str] = set()
    for raw_url in _extract_data_urls(content):
        if "/html" not in raw_url.lower() and not raw_url.lower().endswith(".html"):
            continue
        parts = [part for part in raw_url.split("/") if part]
        for part in reversed(parts):
            if part.isdigit() and len(part) >= 3:
                ids.add(part)
                break

    patterns = [
        r"monthlyStatistics/[^\"']*/(\d+)/html",
        r"yearly/[^\"']*/(\d+)/html",
        r"jsp/[^\"']*/(\d+)/[^\"']*\.html",
    ]
    for pattern in patterns:
        ids.update(re.findall(pattern, content, flags=re.IGNORECASE))
    return ids


class DGCAPortal:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _session()

    def request(self, content_id: str, service_name: str) -> str:
        data = {
            **REQUEST_DATA,
            "contentId": content_id,
            "serviceName": service_name,
        }
        resp = self.session.post(DGCA_SCAN_URL, data=data, timeout=60)
        resp.raise_for_status()
        return resp.text

    def discover_domestic_urls(self) -> list[str]:
        parent = self.request(DGCA_PARENT_CONTENT_ID, "getParentData")
        year_ids = sorted(_extract_html_content_ids(parent))
        print(f"  DGCA domestic discovery: {len(year_ids)} content sections", flush=True)

        visited: set[str] = set()
        urls: set[str] = set()
        for content_id in year_ids:
            urls.update(self._discover_recursive(content_id, visited, depth=0))
        return sorted(urls)

    def _discover_recursive(
        self,
        content_id: str,
        visited: set[str],
        depth: int,
        max_depth: int = 10,
    ) -> set[str]:
        if content_id in visited or depth > max_depth:
            return set()
        visited.add(content_id)

        try:
            content = self.request(content_id, "fetchRulebookContentDtlsList")
        except requests.RequestException as exc:
            print(f"    WARNING: DGCA contentId {content_id} failed: {exc}", flush=True)
            return set()

        urls = _extract_excel_urls(content)
        nested_ids = _extract_html_content_ids(content)
        if _sleep_seconds() > 0:
            time.sleep(_sleep_seconds())

        for nested_id in nested_ids:
            urls.update(self._discover_recursive(nested_id, visited, depth + 1, max_depth))
        return urls


def _cache_urls(path: Path, urls: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(urls) + "\n")


def _read_cached_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def discover_dgca_domestic_urls(refresh: bool = False) -> list[str]:
    cache_path = DGCA_RAW_DIR / "urls" / "domestic.txt"
    cached = _read_cached_urls(cache_path)
    if cached and not refresh:
        print(f"  DGCA domestic discovery: using {len(cached)} cached URLs", flush=True)
        return cached

    urls = DGCAPortal().discover_domestic_urls()
    if urls:
        _cache_urls(cache_path, urls)
    elif cached:
        print("  WARNING: DGCA discovery returned no URLs; using cached manifest", flush=True)
        urls = cached
    return urls


def generate_dgca_international_urls(start_year: int = 2015, end_year: int | None = None) -> list[str]:
    end_year = end_year or date.today().year
    urls: list[str] = []
    for year in range(start_year, end_year + 1):
        yy = str(year)[-2:]
        for quarter in range(1, 5):
            for table in range(1, 5):
                urls.append(
                    f"{DGCA_S3_BASE}/{DGCA_INTERNATIONAL_PATH}/{yy}Q{quarter}_{table}.xlsx"
                )
    _cache_urls(DGCA_RAW_DIR / "urls" / "international.txt", urls)
    return urls


def _filename_for_url(url: str) -> str:
    return unquote(Path(urlparse(url).path).name)


def _dgca_source_url_variants(url: str) -> list[str]:
    """Return common DGCA S3 object-key variants for a discovered workbook URL.

    The DGCA portal sometimes links to a title-case filename while the actual
    S3 object uses uppercase month text, or has one extra space after a comma.
    S3 keys are case-sensitive, so a valid portal link can still return 403.
    """
    parsed = urlparse(url)
    if parsed.netloc != "public-prd-dgca.s3.ap-south-1.amazonaws.com":
        return []

    decoded_path = unquote(parsed.path)
    if DGCA_DOMESTIC_PATH not in decoded_path:
        return []

    directory, filename = decoded_path.rsplit("/", 1)
    month_pattern = "|".join(sorted(MONTH_MAP, key=len, reverse=True))
    match = re.search(rf"\b({month_pattern})\b\s*,?\s*(20\d{{2}})", filename, re.IGNORECASE)
    if not match:
        return []

    month = _clean_key(match.group(1)).replace(" ", "")
    year = match.group(2)
    prefix = filename[: match.start()]
    suffix = filename[match.end() :]
    candidate_names = [
        f"{prefix}{month} {year}{suffix}",
        f"{prefix} {month} {year}{suffix}",
    ]

    variants = []
    for name in candidate_names:
        if name == filename or name in variants:
            continue
        candidate_path = quote(f"{directory}/{name}", safe="/,()._-")
        variants.append(parsed._replace(path=candidate_path).geturl())
    return variants


def download_file(
    url: str,
    dest: Path,
    session: requests.Session,
    started: float,
    force: bool = False,
    quiet_missing: bool = False,
) -> str:
    if not _time_remaining(started):
        return "failed"

    headers: dict[str, str] = {}
    if dest.exists() and not force:
        headers["If-Modified-Since"] = formatdate(dest.stat().st_mtime, usegmt=True)

    urls_to_try = [url, *_dgca_source_url_variants(url)]
    resp = None
    for idx, candidate_url in enumerate(urls_to_try):
        try:
            resp = session.get(candidate_url, headers=headers, stream=True, timeout=120)
        except requests.RequestException as exc:
            print(f"    ERROR downloading {dest.name}: {exc}", flush=True)
            return "failed"

        if resp.status_code in {403, 404} and idx < len(urls_to_try) - 1:
            continue

        if candidate_url != url and resp.status_code < 400:
            print(
                f"    Recovered via filename variant: {_filename_for_url(candidate_url)}",
                flush=True,
            )
        break

    if resp is None:
        return "failed"

    if resp.status_code == 304:
        return "cached"
    if resp.status_code == 404:
        if not quiet_missing:
            print(f"    Missing at source: {dest.name}", flush=True)
        return "missing"

    try:
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"    ERROR downloading {dest.name}: {exc}", flush=True)
        return "failed"

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with open(tmp, "wb") as handle:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)
    tmp.rename(dest)

    if "Last-Modified" in resp.headers:
        try:
            server_dt = parsedate_to_datetime(resp.headers["Last-Modified"])
            os.utime(dest, (server_dt.timestamp(), server_dt.timestamp()))
        except (TypeError, ValueError, OSError):
            pass

    return "downloaded"


def download_urls(
    urls: list[str],
    dest_dir: Path,
    *,
    force: bool = False,
    quiet_missing: bool = False,
) -> DownloadStats:
    session = _session()
    started = time.monotonic()
    stats = DownloadStats()
    for url in urls:
        if not _time_remaining(started):
            print("  Soft timeout reached; stopping source downloads", flush=True)
            break
        dest = dest_dir / _filename_for_url(url)
        status = download_file(
            url,
            dest,
            session=session,
            started=started,
            force=force,
            quiet_missing=quiet_missing,
        )
        stats = stats.add(status)
    return stats


def _excel_files(path: Path) -> list[Path]:
    return sorted(
        file
        for file in path.glob("*")
        if file.suffix.lower() in {".xls", ".xlsx"} and not file.name.endswith(".tmp")
    )


def _display_path(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def parse_domestic_city_file(path: Path) -> pd.DataFrame:
    file_date = _date_from_domestic_city_filename(path)
    if not file_date:
        return pd.DataFrame()
    year, month = file_date

    records = []
    for df in _read_excel_sheets(path):
        header_row = _find_header_row(df, ["TO CITY", "FROM CITY"])
        if header_row is None:
            continue

        header = df.iloc[header_row]
        city1_col = _find_col(header, "CITY", "1")
        city2_col = _find_col(header, "CITY", "2")
        pax_to_col = _find_col(header, "PASSENGER", "TO")
        pax_from_col = _find_col(header, "PASSENGER", "FROM")
        freight_to_col = _find_col(header, "FREIGHT", "TO")
        freight_from_col = _find_col(header, "FREIGHT", "FROM")
        mail_to_col = _find_col(header, "MAIL", "TO")
        mail_from_col = _find_col(header, "MAIL", "FROM")

        required = [city1_col, city2_col, pax_to_col, pax_from_col]
        if any(col is None for col in required):
            continue

        sheet_records = []
        for _, row in df.iloc[header_row + 1 :].iterrows():
            city1 = _clean_key(row[city1_col])
            city2 = _clean_key(row[city2_col])
            if not city1 or not city2 or "TOTAL" in city1:
                continue
            pax_to = _to_number(row[pax_to_col])
            pax_from = _to_number(row[pax_from_col])
            if pax_to is None or pax_from is None:
                continue
            sheet_records.append(
                {
                    "Year": year,
                    "Month": month,
                    "City1": city1,
                    "City2": city2,
                    "PaxToCity2": pax_to,
                    "PaxFromCity2": pax_from,
                    "FreightToCity2": _to_number(row[freight_to_col]) if freight_to_col is not None else 0,
                    "FreightFromCity2": _to_number(row[freight_from_col]) if freight_from_col is not None else 0,
                    "MailToCity2": _to_number(row[mail_to_col]) if mail_to_col is not None else 0,
                    "MailFromCity2": _to_number(row[mail_from_col]) if mail_from_col is not None else 0,
                }
            )
        if sheet_records:
            records.extend(sheet_records)
            break
    return pd.DataFrame.from_records(records)


def aggregate_domestic_city(source_dir: Path, output_dir: Path) -> pd.DataFrame:
    frames = []
    for path in _excel_files(source_dir):
        if "CITYPAIR" not in path.name.upper():
            continue
        parsed = parse_domestic_city_file(path)
        if not parsed.empty:
            frames.append(parsed)
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values(["City1", "City2", "Year", "Month"])
    else:
        combined = pd.DataFrame(
            columns=[
                "Year",
                "Month",
                "City1",
                "City2",
                "PaxToCity2",
                "PaxFromCity2",
                "FreightToCity2",
                "FreightFromCity2",
                "MailToCity2",
                "MailFromCity2",
            ]
        )

    output = output_dir / "domestic" / "city.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output, index=False, float_format="%.2f")
    print(f"  Saved: {_display_path(output)} ({len(combined):,} rows)", flush=True)
    return combined


def _service_type_from_row(row: pd.Series) -> str | None:
    text = " ".join(_clean_key(value) for value in row.tolist())
    if "SERVICE" not in text and "SERVICES" not in text:
        return None
    is_non = "NON" in text
    if "DOMESTIC" in text:
        return "NonScheduledDomestic" if is_non else "ScheduledDomestic"
    if "INTERNATIONAL" in text:
        return "NonScheduledInternational" if is_non else "ScheduledInternational"
    return None


def parse_domestic_carrier_file(path: Path) -> pd.DataFrame:
    year = _source_year_from_filename(path)
    if year is None:
        return pd.DataFrame()
    airline = _normalize_airline(path.stem)
    df = _read_excel(path)

    records = []
    current_type: str | None = None
    for _, row in df.iterrows():
        service_type = _service_type_from_row(row)
        if service_type:
            current_type = service_type
            continue

        month_col = None
        month = None
        for col, value in row.items():
            month = _month_number(value)
            if month:
                month_col = int(col)
                break
        if not month or current_type is None:
            continue

        values = []
        for col in range(month_col + 1, month_col + 17):
            values.append(_to_number(row[col]) if col in row.index else None)
        if len(values) != 16 or values[3] is None:
            continue

        records.append(
            {
                "Type": current_type,
                "Airline": airline,
                "Year": year,
                "Month": month,
                "Aircraft Number": values[0],
                "Aircraft Hours": values[1],
                "Aircraft Kilometres": values[2],
                "Passenger Number": values[3],
                "Passenger Kilometers": values[4],
                "Seat Kilometers": values[5],
                "Passenger Load Factor": values[6],
                "Freight": values[7],
                "Mail": values[8],
                "Total Cargo": values[9],
                "Passenger Tonne Kilometer": values[10],
                "Mail Tonne Kilometer": values[12],
                "Freight Tonne Kilometer": values[11],
                "Total Tonne Kilometer": values[13],
                "Available Tonne Kilometer": values[14],
                "Weight Load Factor": values[15],
            }
        )
    return pd.DataFrame.from_records(records)


def aggregate_domestic_carrier(source_dir: Path, output_dir: Path) -> pd.DataFrame:
    frames = []
    for path in _excel_files(source_dir):
        if "CITYPAIR" in path.name.upper():
            continue
        parsed = parse_domestic_carrier_file(path)
        if not parsed.empty:
            frames.append(parsed)

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined = combined[DOMESTIC_CARRIER_COLUMNS]
        combined = combined.sort_values(["Type", "Airline", "Year", "Month"])
    else:
        combined = pd.DataFrame(columns=DOMESTIC_CARRIER_COLUMNS)

    output = output_dir / "domestic" / "carrier.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output, index=False, float_format="%.3f")
    print(f"  Saved: {_display_path(output)} ({len(combined):,} rows)", flush=True)
    return combined


def _international_meta(path: Path) -> tuple[int, int, str] | None:
    match = re.search(r"(\d{2})Q([1-4])_([1-4])", path.stem, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), match.group(3)


def _parse_international_table(path: Path, table: str) -> pd.DataFrame:
    meta = _international_meta(path)
    if not meta:
        return pd.DataFrame()
    year, quarter, _ = meta
    df = _read_excel(path)

    records = []
    for _, row in df.iterrows():
        first = _to_number(row.iloc[0] if len(row) else None)
        if first is None:
            continue

        if table == "1" and len(row) >= 6:
            airline = _clean_key(row.iloc[1])
            if not airline or "TOTAL" in airline:
                continue
            records.append(
                {
                    "Year": year,
                    "Quarter": quarter,
                    "Airline": airline,
                    "PaxToIndia": _to_number(row.iloc[2]),
                    "PaxFromIndia": _to_number(row.iloc[3]),
                    "FreightToIndia": _to_number(row.iloc[4]),
                    "FreightFromIndia": _to_number(row.iloc[5]),
                }
            )
        elif table == "2" and len(row) >= 14:
            airline = _clean_key(row.iloc[1])
            if not airline or "TOTAL" in airline:
                continue
            records.append(
                {
                    "Year": year,
                    "Quarter": quarter,
                    "Airline": airline,
                    "PaxToIndiaM1": _to_number(row.iloc[2]),
                    "PaxFromIndiaM1": _to_number(row.iloc[3]),
                    "FreightToIndiaM1": _to_number(row.iloc[4]),
                    "FreightFromIndiaM1": _to_number(row.iloc[5]),
                    "PaxToIndiaM2": _to_number(row.iloc[6]),
                    "PaxFromIndiaM2": _to_number(row.iloc[7]),
                    "FreightToIndiaM2": _to_number(row.iloc[8]),
                    "FreightFromIndiaM2": _to_number(row.iloc[9]),
                    "PaxToIndiaM3": _to_number(row.iloc[10]),
                    "PaxFromIndiaM3": _to_number(row.iloc[11]),
                    "FreightToIndiaM3": _to_number(row.iloc[12]),
                    "FreightFromIndiaM3": _to_number(row.iloc[13]),
                }
            )
        elif table == "3" and len(row) >= 6:
            country = _clean_key(row.iloc[1])
            if not country or "TOTAL" in country:
                continue
            records.append(
                {
                    "Year": year,
                    "Quarter": quarter,
                    "Country": country,
                    "PaxToIndia": _to_number(row.iloc[2]),
                    "PaxFromIndia": _to_number(row.iloc[3]),
                    "FreightToIndia": _to_number(row.iloc[4]),
                    "FreightFromIndia": _to_number(row.iloc[5]),
                }
            )
        elif table == "4" and len(row) >= 7:
            city1 = _clean_key(row.iloc[1])
            city2 = _clean_key(row.iloc[2])
            if not city1 or not city2 or "TOTAL" in city1:
                continue
            records.append(
                {
                    "Year": year,
                    "Quarter": quarter,
                    "City1": city1,
                    "City2": city2,
                    "PaxToCity2": _to_number(row.iloc[3]),
                    "PaxFromCity2": _to_number(row.iloc[4]),
                    "FreightToCity2": _to_number(row.iloc[5]),
                    "FreightFromCity2": _to_number(row.iloc[6]),
                }
            )
    return pd.DataFrame.from_records(records)


def aggregate_international(source_dir: Path, output_dir: Path) -> dict[str, pd.DataFrame]:
    outputs = {
        "1": ("carrier_quarterly", ["Airline", "Year", "Quarter"]),
        "2": ("carrier", ["Airline", "Year", "Quarter"]),
        "3": ("country", ["Country", "Year", "Quarter"]),
        "4": ("city", ["City1", "City2", "Year", "Quarter"]),
    }
    result: dict[str, pd.DataFrame] = {}
    for table, (filename, sort_cols) in outputs.items():
        frames = [
            _parse_international_table(path, table)
            for path in _excel_files(source_dir)
            if path.stem.upper().endswith(f"_{table}")
        ]
        frames = [frame for frame in frames if not frame.empty]
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if not combined.empty:
            combined = combined.sort_values(sort_cols)

        output = output_dir / "international" / f"{filename}.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(output, index=False, float_format="%.2f")
        print(f"  Saved: {_display_path(output)} ({len(combined):,} rows)", flush=True)
        result[filename] = combined
    return result


def aggregate_all() -> None:
    print("\n── Aggregating official source files ──", flush=True)
    aggregate_domestic_city(DGCA_RAW_DIR / "xlsx" / "domestic", AGGREGATED_DIR)
    aggregate_domestic_carrier(DGCA_RAW_DIR / "xlsx" / "domestic", AGGREGATED_DIR)
    aggregate_international(DGCA_RAW_DIR / "xlsx" / "international", AGGREGATED_DIR)


def ingest_aviation_sources(
    *,
    force: bool = False,
    refresh_urls: bool = True,
    aggregate: bool = True,
    timeout_started_at: float | None = None,
) -> None:
    global _TIMEOUT_STARTED_AT
    _TIMEOUT_STARTED_AT = timeout_started_at or time.monotonic()

    print("\n── Official aviation sources ──", flush=True)
    domestic_urls = discover_dgca_domestic_urls(refresh=refresh_urls)
    international_urls = generate_dgca_international_urls()

    print(f"  Downloading DGCA domestic files: {len(domestic_urls):,}", flush=True)
    domestic_stats = download_urls(
        domestic_urls,
        DGCA_RAW_DIR / "xlsx" / "domestic",
        force=force,
    )
    print(f"    {domestic_stats}", flush=True)

    print(f"  Downloading DGCA international candidates: {len(international_urls):,}", flush=True)
    international_stats = download_urls(
        international_urls,
        DGCA_RAW_DIR / "xlsx" / "international",
        force=force,
        quiet_missing=True,
    )
    print(f"    {international_stats}", flush=True)

    if aggregate:
        aggregate_all()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="redownload existing files")
    parser.add_argument(
        "--use-cached-urls",
        action="store_true",
        help="reuse cached DGCA domestic URL manifest instead of rediscovering",
    )
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="skip network downloads and rebuild aggregate CSVs from local raw files",
    )
    args = parser.parse_args()

    if args.aggregate_only:
        aggregate_all()
        return

    ingest_aviation_sources(
        force=args.force,
        refresh_urls=not args.use_cached_urls,
    )


if __name__ == "__main__":
    main()
