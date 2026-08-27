#!/usr/bin/env python3

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PRIMARY_API_URL = "https://api.alternative.me/fng/?limit=1&format=json"
OFFICIAL_API_URLS = (
    PRIMARY_API_URL,
    "https://api.alternative.me/fng/",
)
OUTPUT = Path("latest.json")
MAX_SOURCE_AGE_SECONDS = 72 * 60 * 60
FUTURE_TOLERANCE_SECONDS = 10 * 60
URLLIB_ATTEMPTS_PER_URL = 3
ALLOWED_CLASSIFICATIONS = {
    "Extreme Fear",
    "Fear",
    "Neutral",
    "Greed",
    "Extreme Greed",
}


def parse_and_validate(raw: str):
    if not raw.strip():
        raise ValueError("empty response body")

    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("metadata is missing or invalid")
    if metadata.get("error") not in (None, ""):
        raise ValueError(f"API metadata.error is not null: {metadata.get('error')}")

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("data[0] is missing")

    item = data[0]
    if not isinstance(item, dict):
        raise ValueError("data[0] must be an object")

    for field in ("value", "value_classification", "timestamp"):
        if field not in item or item[field] in (None, ""):
            raise ValueError(f"required field missing: data[0].{field}")

    try:
        value = int(item["value"])
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not an integer") from exc
    if not 0 <= value <= 100:
        raise ValueError(f"value out of range: {value}")

    # Alternative.me itself returns value_classification. Treat the official
    # classification as the source of truth instead of imposing local numeric
    # boundaries that could become stale if the provider changes its scheme.
    classification = str(item["value_classification"]).strip()
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise ValueError(f"unexpected value_classification: {classification!r}")

    try:
        timestamp = int(item["timestamp"])
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp is not a Unix integer") from exc

    now = int(time.time())
    if timestamp > now + FUTURE_TOLERANCE_SECONDS:
        raise ValueError(
            f"timestamp is too far in the future: {timestamp} > {now} + {FUTURE_TOLERANCE_SECONDS}"
        )

    source_age_seconds = max(0, now - timestamp)
    if source_age_seconds >= MAX_SOURCE_AGE_SECONDS:
        raise ValueError(
            f"timestamp is too old: age={source_age_seconds}s "
            f"(limit < {MAX_SOURCE_AGE_SECONDS}s)"
        )

    time_until_update = item.get("time_until_update")
    if time_until_update not in (None, ""):
        try:
            time_until_update = int(time_until_update)
        except (TypeError, ValueError):
            time_until_update = None

    return {
        "value": value,
        "value_classification": classification,
        "timestamp": timestamp,
        "source_age_seconds": source_age_seconds,
        "time_until_update": time_until_update,
    }


def fetch_with_urllib(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "crypto-fear-greed-monitor/2.0 (+https://github.com/zzt372/crypto-fear-greed-monitor)",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=20) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"unexpected HTTP status: {status}")
        return response.read().decode("utf-8")


def fetch_with_curl(url: str) -> str:
    result = subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "--retry-all-errors",
            "--connect-timeout",
            "10",
            "--max-time",
            "30",
            "--header",
            "Accept: application/json",
            "--header",
            "Cache-Control: no-cache",
            "--user-agent",
            "crypto-fear-greed-monitor/2.0 (+https://github.com/zzt372/crypto-fear-greed-monitor)",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout


def fetch_latest_valid():
    errors = []

    for url in OFFICIAL_API_URLS:
        for attempt in range(1, URLLIB_ATTEMPTS_PER_URL + 1):
            try:
                raw = fetch_with_urllib(url)
                validated = parse_and_validate(raw)
                return validated, url, f"urllib-attempt-{attempt}"
            except (
                HTTPError,
                URLError,
                TimeoutError,
                json.JSONDecodeError,
                UnicodeDecodeError,
                ValueError,
                RuntimeError,
            ) as exc:
                message = f"urllib {url} attempt {attempt}: {type(exc).__name__}: {exc}"
                errors.append(message)
                print(message, file=sys.stderr)
                if attempt < URLLIB_ATTEMPTS_PER_URL:
                    time.sleep(2 * attempt)

        try:
            raw = fetch_with_curl(url)
            validated = parse_and_validate(raw)
            return validated, url, "curl-with-retry"
        except (
            subprocess.SubprocessError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
            RuntimeError,
        ) as exc:
            message = f"curl {url}: {type(exc).__name__}: {exc}"
            errors.append(message)
            print(message, file=sys.stderr)

    summary = " | ".join(errors[-6:])
    raise RuntimeError(f"all official API retrieval paths failed: {summary}")


def main():
    validated, endpoint_used, fetch_method = fetch_latest_valid()
    now = datetime.now(timezone.utc)
    timestamp = validated["timestamp"]

    output = {
        "schema_version": 2,
        "ok": True,
        "value": validated["value"],
        "value_classification": validated["value_classification"],
        "timestamp": timestamp,
        "timestamp_iso": datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "source_age_seconds": validated["source_age_seconds"],
        "time_until_update": validated["time_until_update"],
        "source": "Alternative.me official API",
        "endpoint": endpoint_used,
        "fetch_method": fetch_method,
    }

    # Atomic replace only after retrieval, JSON parsing, and validation all
    # succeed. Any failure leaves the previous known-good latest.json intact.
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(OUTPUT)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
