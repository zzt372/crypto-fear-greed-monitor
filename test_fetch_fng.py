import json
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError

import fetch_fng


def valid_payload(**overrides):
    item = {
        "value": "71",
        "value_classification": "Greed",
        "timestamp": str(int(time.time()) - 3600),
        "time_until_update": "72000",
    }
    item.update(overrides)
    return json.dumps(
        {
            "name": "Fear and Greed Index",
            "data": [item],
            "metadata": {"error": None},
        }
    )


class ParseAndValidateTests(unittest.TestCase):
    def test_accepts_valid_official_payload(self):
        result = fetch_fng.parse_and_validate(valid_payload())
        self.assertEqual(result["value"], 71)
        self.assertEqual(result["value_classification"], "Greed")
        self.assertIsInstance(result["timestamp"], int)

    def test_rejects_out_of_range_value(self):
        with self.assertRaises(ValueError):
            fetch_fng.parse_and_validate(valid_payload(value="101"))

    def test_rejects_unknown_classification(self):
        with self.assertRaises(ValueError):
            fetch_fng.parse_and_validate(
                valid_payload(value_classification="Something Else")
            )

    def test_rejects_api_metadata_error(self):
        payload = json.dumps(
            {
                "data": [
                    {
                        "value": "71",
                        "value_classification": "Greed",
                        "timestamp": str(int(time.time()) - 3600),
                    }
                ],
                "metadata": {"error": "upstream error"},
            }
        )
        with self.assertRaises(ValueError):
            fetch_fng.parse_and_validate(payload)

    def test_rejects_stale_source_timestamp(self):
        stale = int(time.time()) - fetch_fng.MAX_SOURCE_AGE_SECONDS - 1
        with self.assertRaises(ValueError):
            fetch_fng.parse_and_validate(valid_payload(timestamp=str(stale)))

    def test_allows_small_future_clock_skew(self):
        near_future = int(time.time()) + 60
        result = fetch_fng.parse_and_validate(valid_payload(timestamp=str(near_future)))
        self.assertEqual(result["source_age_seconds"], 0)


class FetchFallbackTests(unittest.TestCase):
    @patch("fetch_fng.time.sleep", return_value=None)
    @patch("fetch_fng.fetch_with_curl")
    @patch("fetch_fng.fetch_with_urllib")
    def test_falls_back_to_curl_after_urllib_failures(
        self, mock_urllib, mock_curl, _mock_sleep
    ):
        mock_urllib.side_effect = URLError("temporary DNS failure")
        mock_curl.return_value = valid_payload()

        result, endpoint, method = fetch_fng.fetch_latest_valid()

        self.assertEqual(result["value"], 71)
        self.assertIn(endpoint, fetch_fng.OFFICIAL_API_URLS)
        self.assertEqual(method, "curl-with-retry")
        self.assertEqual(mock_urllib.call_count, fetch_fng.URLLIB_ATTEMPTS_PER_URL)
        self.assertEqual(mock_curl.call_count, 1)


if __name__ == "__main__":
    unittest.main()
