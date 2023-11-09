from __future__ import annotations

import logging
import urllib.parse
import uuid
import httpx
import sentry_sdk
import pathlib
from sentry_sdk.integrations.atexit import AtexitIntegration
from typing import Any, Dict, Optional
from filelock import FileLock


from dataclasses import dataclass

logger = logging.getLogger(__name__)

BEARER_AUTH_URL = "/api/authz/v3/oauth/token"


class Auth:
    pass


@dataclass
class CookieAuth(Auth):
    username: str
    password: str


@dataclass
class BearerAuth(Auth):
    client_id: str
    client_secret: str


def fetch_crashes_from_server(
    server_url: str, crash_endpoint: str, auth: Auth, latest_id: int = 0
) -> Dict[str, Any]:
    headers = {
        "Accept": "application/vnd.scea.recap.crashes+json; version=1",
        "Content-Type": "application/json; charset=utf-8",
    }
    crash_url = f"{server_url}{crash_endpoint}"

    # # For initial query, we limit number of crashes to 1_000 items, which is the default of Recap Server,
    # # and for all following requests, we do not limit the number, as it's already capped at 10_000 by the server.
    # # For non-initial queries, we want to filter for all events that happened _after_ our previously
    # # fetched crashes, base on the most recent ID.
    if latest_id == 0:
        crash_url = f"{crash_url};limit=1000"
    else:
        # Apache Solr format requires us to encode the query.
        # Exclusive bounds range - {N TO *}
        crash_url = crash_url + urllib.parse.quote(f";q=id:{{{latest_id} TO *}}", safe=";=:")

    with httpx.Client() as client:
        if isinstance(auth, BearerAuth):
            res = client.post(
                f"{server_url}{BEARER_AUTH_URL}",
                auth=(auth.client_id, auth.client_secret),
                data={"grant_type": "client_credentials", "scope": "psn:backoffice"},
            )
            bearer_token = res.json()["access_token"]
            if bearer_token:
                logger.debug("Successfully fetched bearer token")
            headers["Authorization"] = f"Bearer {bearer_token}"
        elif isinstance(auth, CookieAuth):
            login_url = f"{server_url}/login.jsp"
            client.post(login_url, data={"username": auth.username, "password": auth.password})
            assert client.cookies["JSESSIONID"]
        res = client.get(crash_url, headers=headers)
        data = res.json()
        crashes: Dict[str, Any] = data["_embedded"]["crash"]
        logger.debug(f"Found {len(crashes)} crashes")
        return crashes

def sync_crashes_sentry(
    base_url: str,
    crash_endpoint: str,
    auth: Auth,
    sentry_dsn: str,
    state_file_path: pathlib.Path,
) -> None:
    

    lock = FileLock(f"{state_file_path}.lock")
    with lock:
        if state_file_path.exists():
            latest_id = int(state_file_path.read_text())
        else:
            latest_id = 0

        logger.debug(f"Initializing Sentry SDK with DSN {sentry_dsn}")
        sentry_sdk.init(
            sentry_dsn,
            max_breadcrumbs=0,
            enable_tracing=False,
            default_integrations=False,
            #integrations=[
            #    AtexitIntegration(),
            #],
        )
        for crash in fetch_crashes_from_server(base_url, crash_endpoint, auth, latest_id=latest_id):
            latest_id = max(latest_id, crash["id"])
            event = construct_event(crash)
            sentry_sdk.capture_event(event)
            sentry_sdk.flush()
        logger.debug(f"Writing latest ID {latest_id} to state file {state_file_path}")
        state_file_path.write_text(str(latest_id))


def construct_event(crash: dict[str, Any]) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_id": uuid.uuid4().hex,
        "sdk": {"name": "recap.uploader.sdk", "version": "0.1.0"},
        "server_name": None,
        "platform": "native",
        "exception": {
            "values": [
                {
                    "type": crash["stopReason"],
                }
            ]
        },
        "tags": {
            "id": crash["id"],
        },
        "contexts": {
            "request": {"url": crash["_links"]["self"]},
        },
    }

    if "uploadDate" in crash:
        event["timestamp"] = crash["uploadDate"]

    if "stopLocation" in crash:
        event["exception"]["values"][0]["value"] = crash["stopLocation"]
    elif "returnLocation" in crash:
        event["exception"]["values"][0]["value"] = crash["returnLocation"]

    if "detailedStackTrace" in crash:
        frames = []
        for frame in crash["detailedStackTrace"]:
            processed_frame = {
                "filename": frame["sourceFile"],
                "lineno": frame["sourceLine"],
                "instruction_addr": frame["absoluteAddress"],
                "module": frame["moduleName"],
                "function": frame["resolvedSymbol"],
                "raw_function": frame["displayValue"],
                "in_app": True,
            }
            frames.append(processed_frame)
        event["exception"]["values"][0]["stacktrace"] = {"frames": frames}
    elif "stackTrace" in crash:
        frames = []
        for frame in crash["stackTrace"]:
            processed_frame = {"function": frame, "in_app": True}
            frames.append(processed_frame)
        event["exception"]["values"][0]["stacktrace"] = {"frames": frames}

    if "titleId" in crash:
        event["tags"]["titleId"] = crash["titleId"]

    if "platform" in crash:
        if "sysVersion" in crash:
            event["contexts"]["runtime"] = {
                "name": crash["platform"],
                "version": crash["sysVersion"],
            }

        if "hardwareId" in crash:
            event["contexts"]["device"] = {
                "name": crash["platform"],
                "model_id": crash["hardwareId"],
            }

    if "appVersion" in crash:
        event["contexts"]["app"] = {"app_version": crash["appVersion"]}

    if "userData" in crash:
        event["contexts"]["userData"] = crash["userData"]

    return event
