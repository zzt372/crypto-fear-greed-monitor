#!/usr/bin/env python3

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.alternative.me/fng/?limit=1&format=json"
OUTPUT = Path("latest.json")
MAX_AGE_SECONDS = 48 * 60 * 60
ATTEMPTS = 3
ALLOWED_CLASSIFICATIONS = {
    "Extreme Fear",
    "Fear",
    "Neutral",
    "Greed",
    "Extreme Greed",
}


def fetch_json():
    last_error = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            request = Request(
                API_URL,
                headers={
                    "User-Agent": "crypto-fear-greed-monitor/1.0 (+https://github.com/zzt372/crypto-fear-greed-monitor)",
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=20) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise RuntimeError(f"unexpected HTTP status: {status}")
                raw = response.read().decode("utf-8")
                if not raw.strip():
                    raise RuntimeError("empty response body")
                return json.loads(raw)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            print(f"Attempt {attempt}/{ATTEMPTS} failed: {exc}", file=sys.stderr)
            if attempt < ATTEMPTS:
                time.sleep(5 * attempt)

    raise RuntimeError(f"Alternative.me API failed after {ATTEMPTS} attempts: {last_error}")


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")

    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("error") not in (None, ""):
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

    classification = str(item["value_classification"]).strip()
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise ValueError(f"unexpected value_classification: {classification!r}")

    try:
        timestamp = int(item["timestamp"])
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp is not a Unix integer") from exc

    now = int(time.time())
    if timestamp > now:
        raise ValueError(f"timestamp is in the future: {timestamp} > {now}")
    age = now - timestamp
    if age >= MAX_AGE_SECONDS:
        raise ValueError(f"timestamp is too old: age={age}s (limit < {MAX_AGE_SECONDS}s)")

    return value, classification, timestamp


def main():
    payload = fetch_json()
    value, classification, timestamp = validate(payload)
    now = datetime.now(timezone.utc)

    output = {
        "ok": True,
        "value": value,
        "value_classification": classification,
        "timestamp": timestamp,
        "timestamp_iso": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "source": "Alternative.me official API",
        "endpoint": API_URL,
    }

    # Write only after every validation succeeds. On fetch/validation failure,
    # the previous latest.json remains untouched.
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUTPUT)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
