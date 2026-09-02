import json
import unittest
from unittest.mock import Mock

import requests

from scripts.data_service_connect import (
    CreditCallNotApproved,
    DataServiceClient,
    DataServiceError,
)


def response(status, payload=None):
    result = requests.Response()
    result.status_code = status
    result.reason = "test"
    result._content = b"" if payload is None else json.dumps(payload).encode()
    if payload is not None:
        result.headers["Content-Type"] = "application/json"
    return result


class DataServiceClientTests(unittest.TestCase):
    def client(self, session):
        return DataServiceClient("user", "password", session=session)

    def test_authenticates_once_and_reuses_token(self):
        session = Mock()
        session.post.return_value = response(200, {"token": "secret-token"})
        session.request.side_effect = [response(200, {"companies": []}), response(200, {})]
        client = self.client(session)

        client.search_companies(countries="US", name="Example")
        client.request_json("GET", "/countries")

        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(client.stats.authentications, 1)
        self.assertEqual(client.stats.api_requests, 2)

    def test_reauthenticates_once_after_401(self):
        session = Mock()
        session.post.side_effect = [
            response(200, {"token": "old"}),
            response(200, {"token": "new"}),
        ]
        session.request.side_effect = [response(401, {"message": "expired"}), response(200, {})]
        client = self.client(session)

        client.request_json("GET", "/countries")

        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(session.request.call_count, 2)

    def test_blocks_unapproved_credit_call(self):
        session = Mock()
        client = self.client(session)

        with self.assertRaises(CreditCallNotApproved):
            client.request_json("GET", "/companies/US-1", credit_consuming=True)

        session.post.assert_not_called()

    def test_auth_error_does_not_include_response_body(self):
        session = Mock()
        session.post.return_value = response(401, {"message": "password=do-not-log"})
        client = self.client(session)

        with self.assertRaises(DataServiceError) as caught:
            client.authenticate()

        self.assertNotIn("do-not-log", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
