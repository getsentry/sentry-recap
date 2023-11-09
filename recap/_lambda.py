import logging
import tempfile
import platform
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from ._recap import sync_crashes_sentry, CookieAuth, BearerAuth, Auth


class Options(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTRY_RECAP_")

    base_url: AnyHttpUrl
    crash_endpoint: str
    sentry_dsn: str
    cookie_auth: str | None = None
    bearer_auth: str | None = None
    state_file_path: Path | None = None


def lambda_handler(event, context):
    fmt = "[%(levelname)s] %(asctime)s | %(name)s - - %(message)s"
    lvl = logging.DEBUG

    logging.basicConfig(level=lvl, format=fmt)
    options = Options()
    if not options.state_file_path:
        tmp = Path("/tmp" if platform.system() == "Darwin" else tempfile.gettempdir())
        server_name = options.base_url.host
        options.state_file_path = Path(tmp, "{server_name}.state")

    if options.cookie_auth and not options.bearer_auth:
        username, password = options.cookie_auth.split(":")
        auth: Auth = CookieAuth(username=username, password=password)

    elif options.bearer_auth and not options.cookie_auth:
        client_id, client_secret = options.bearer_auth.split(":")
        auth: Auth = BearerAuth(client_id=client_id, client_secret=client_secret)

    sync_crashes_sentry(
        options.base_url, options.crash_endpoint, auth, options.sentry_dsn, options.state_file_path
    )
