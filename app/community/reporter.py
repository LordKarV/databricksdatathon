"""Reporter key: a pseudonym for the signed-in health worker, so reports can be counted per person, never named.

Behind Databricks Apps the proxy sets X-Forwarded-User (the user id) and X-Forwarded-Email on every request. We
keep only HMAC-SHA256(REPORTER_KEY, user)[:16]. REPORTER_KEY is a Databricks secret bound in app.yaml:

    env:
      - name: REPORTER_KEY
        valueFrom: reporter-key      # app resource: secret scope referral-saathi, key reporter-key, READ

Without the key (local runs, or the secret not bound) the key is None: the report is still stored, but it is not
rate limited and does not count as a distinct reporter in field.py.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping

KEY_HEX = 16


def reporter_key(headers: Mapping[str, str]) -> str | None:
    secret = os.environ.get("REPORTER_KEY")
    user = (headers.get("x-forwarded-user") or headers.get("x-forwarded-email") or "").strip().lower()
    if not secret or not user:
        return None
    return hmac.new(secret.encode(), user.encode(), hashlib.sha256).hexdigest()[:KEY_HEX]
