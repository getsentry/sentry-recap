import logging

import typer
from typing_extensions import Annotated, Optional
from pathlib import Path

from ._recap import BearerAuth, CookieAuth, Auth,  sync_crashes_sentry

logger = logging.getLogger(__name__)
app = typer.Typer()

@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    fmt = "[%(levelname)s] %(asctime)s | %(name)s - - %(message)s"
    lvl = logging.DEBUG if verbose else logging.ERROR

    logging.basicConfig(level=lvl, format=fmt)


@app.command()
def sync(
    base_url: Annotated[str, typer.Argument(help="CRS/Recap URL")],
    crash_endpoint: Annotated[str, typer.Argument(help="CRS/Recap Crash Endpoint")],
    sentry_dsn: Annotated[str, typer.Argument(help="Sentry DSN")],
    cookie_auth: Annotated[str, typer.Option(help="Cookie auth <username>:<password>")] = None,
    bearer_auth: Annotated[str, typer.Option(help="Bearer auth <client-id>:<client-secret>")] = None,
    state_file_path: Annotated[
        Optional[Path],
        typer.Option(
           help="Path to state file",
           file_okay=True,
           dir_okay=False,
           writable=True,
           readable=True,
           resolve_path=True,
        )] = None,
) -> None:
    """Sync crashes CRS/Recap Server to Sentry"""

    if state_file_path is None:
        server_name = base_url.split("//")[1].replace("/", ".")
        state_file_path = Path(f"{server_name}.state")

    if cookie_auth and not bearer_auth:
        username, password = cookie_auth.split(":")
        auth: Auth = CookieAuth(username=username, password=password)
        
    elif bearer_auth and not cookie_auth:
        client_id, client_secret = bearer_auth.split(":")
        auth: Auth = BearerAuth(client_id=client_id, client_secret=client_secret)
    else:
        raise typer.BadParameter("Either cookie_auth or bearer_auth must be provided")
    sync_crashes_sentry(base_url, crash_endpoint, auth, sentry_dsn, state_file_path)
