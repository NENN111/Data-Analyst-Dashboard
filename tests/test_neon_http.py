import unittest
from unittest.mock import MagicMock, patch

import requests
import pandas as pd
from sqlalchemy import text

from neon_http import neon_http_endpoint, read_neon_sql


class NeonHttpTest(unittest.TestCase):
    connection = "postgresql://user:password@ep-example-pooler.c-7.us-east-2.aws.neon.tech/db?sslmode=require"

    def setUp(self):
        patcher = patch("neon_http.database_url", return_value=self.connection)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def response(status=200, result=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.json.return_value = result or {"fields": [], "rows": []}
        return response

    def test_credentials_are_only_sent_to_neon_without_redirects(self):
        with patch("neon_http.requests.post", return_value=self.response()) as post:
            read_neon_sql(text("SELECT :title").bindparams(title="Data Analyst"))
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.c-7.us-east-2.aws.neon.tech/sql")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (5, 15))
        self.assertEqual(kwargs["json"], {"query": "SELECT $1", "params": ["Data Analyst"]})

    def test_other_database_hosts_cannot_receive_neon_credentials(self):
        with (
            patch("neon_http.database_url", return_value="postgresql://user:password@localhost/db"),
            patch("neon_http.requests.post") as post,
        ):
            self.assertIsNone(neon_http_endpoint())
            with self.assertRaises(ValueError):
                read_neon_sql(text("SELECT 1"))
        post.assert_not_called()

    def test_raw_database_values_are_converted_for_dashboard(self):
        result = {
            "fields": [
                {"name": "id", "dataTypeID": 20},
                {"name": "skills", "dataTypeID": 114},
                {"name": "salary_gross", "dataTypeID": 16},
                {"name": "published_at", "dataTypeID": 1184},
                {"name": "median_salary", "dataTypeID": 1700},
            ],
            "rows": [
                ["9007199254740993", '["SQL", "Python"]', "t", "2026-10-07 12:00:00+00", "125000.5"],
                ["9007199254740994", "[]", None, None, None],
            ],
        }
        with patch("neon_http.requests.post", return_value=self.response(result=result)):
            frame = read_neon_sql(text("SELECT * FROM vacancies"))
        self.assertEqual(frame.iloc[0]["id"], 9007199254740993)
        self.assertEqual(frame.iloc[0]["skills"], ["SQL", "Python"])
        self.assertTrue(frame.iloc[0]["salary_gross"])
        self.assertTrue(pd.isna(frame.iloc[1]["salary_gross"]))
        self.assertEqual(frame.iloc[0]["published_at"].year, 2026)
        self.assertEqual(frame.iloc[0]["median_salary"], 125000.5)

    def test_timeout_stops_after_two_attempts_without_exposing_credentials(self):
        with (
            patch("neon_http.requests.post", side_effect=requests.Timeout(self.connection)) as post,
            patch("neon_http.time.sleep"),
        ):
            with self.assertRaises(RuntimeError) as caught:
                read_neon_sql(text("SELECT 1"))
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("password", str(caught.exception))

    def test_authentication_error_is_not_retried(self):
        with (
            patch("neon_http.requests.post", return_value=self.response(status=401)) as post,
            patch("neon_http.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "401"):
                read_neon_sql(text("SELECT 1"))
        post.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
