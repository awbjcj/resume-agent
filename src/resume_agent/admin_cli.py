from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import typer

CREDENTIALS_PATH = Path.home() / ".resume-agent" / "credentials.json"
DEFAULT_URL = "http://localhost:8000"
admin_app = typer.Typer(help="Manage users on a deployed Resume Agent instance.")


def api_url() -> str:
    return os.environ.get("RESUME_AGENT_URL", DEFAULT_URL).rstrip("/")


def _make_client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=30)


def load_credentials() -> dict[str, str] | None:
    try:
        value = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    required = {"apiUrl", "username", "token"}
    return value if isinstance(value, dict) and required <= value.keys() else None


def _save_credentials(credentials: dict[str, str]) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    try:
        CREDENTIALS_PATH.chmod(0o600)
    except OSError:
        pass


def _fail(message: str) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(1)


def _check(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        try:
            error = response.json()["error"]
            raise _fail(f"{error['code']}: {error['message']}")
        except (KeyError, ValueError):
            raise _fail(f"HTTP {response.status_code}")
    return response.json() if response.content else {}


def _authed_client() -> httpx.Client:
    credentials = load_credentials()
    if credentials is None:
        raise _fail("Not logged in. Run: resume-agent admin login")
    client = _make_client(credentials["apiUrl"])
    client.headers["Authorization"] = f"Bearer {credentials['token']}"
    return client


def _user_id(client: httpx.Client, username: str) -> str:
    for user in _check(client.get("/api/admin/users"))["users"]:
        if user["username"] == username or user["id"] == username:
            return user["id"]
    raise _fail(f"user {username!r} not found")


def do_login(url: str, username: str, password: str) -> None:
    with _make_client(url) as client:
        _check(
            client.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
        )
        token = _check(client.post("/api/account/tokens", json={"name": "cli"}))
    _save_credentials({"apiUrl": url, "username": username, "token": token["token"]})
    typer.echo(f"Logged in as {username} at {url}")


def do_logout() -> None:
    CREDENTIALS_PATH.unlink(missing_ok=True)
    typer.echo("Logged out.")


def do_whoami() -> None:
    credentials = load_credentials()
    typer.echo(
        "Not logged in."
        if credentials is None
        else f"{credentials['username']} -> {credentials['apiUrl']}"
    )


def do_list_users() -> None:
    with _authed_client() as client:
        users = _check(client.get("/api/admin/users"))["users"]
    typer.echo(f"{'USERNAME':<20}{'ROLE':<8}{'USAGE':>12}{'JOBS':>7}  LIMITS")
    for user in users:
        limits = "/".join(
            "default" if user[key] is None else str(user[key])
            for key in ("weeklyTokenBudget", "maxActiveJobs", "maxConcurrentRuns")
        )
        disabled = " [disabled]" if user["disabledAt"] else ""
        typer.echo(
            f"{user['username']:<20}{user['role']:<8}{user['weeklyUsage']:>12,.0f}"
            f"{user['activeJobs']:>7}  {limits}{disabled}"
        )


def do_invite(expires_days: int = 14) -> None:
    with _authed_client() as client:
        invite = _check(
            client.post("/api/admin/invites", json={"expiresInDays": expires_days})
        )
    typer.echo(f"Invite (expires {invite['expiresAt']}): {invite['code']}")


def do_patch_user(username: str, payload: dict) -> None:
    with _authed_client() as client:
        user_id = _user_id(client, username)
        _check(client.patch(f"/api/admin/users/{user_id}", json=payload))


def do_set_role(username: str, role: str) -> None:
    do_patch_user(username, {"role": role})


def do_set_limits(
    username: str,
    budget: int | None = None,
    max_jobs: int | None = None,
    max_runs: int | None = None,
) -> None:
    payload = {
        key: value
        for key, value in {
            "weeklyTokenBudget": budget,
            "maxActiveJobs": max_jobs,
            "maxConcurrentRuns": max_runs,
        }.items()
        if value is not None
    }
    if not payload:
        raise _fail("nothing to set")
    do_patch_user(username, payload)


def do_set_disabled(username: str, disabled: bool) -> None:
    do_patch_user(username, {"disabled": disabled})


def do_delete(username: str) -> None:
    with _authed_client() as client:
        user_id = _user_id(client, username)
        _check(
            client.delete(f"/api/admin/users/{user_id}", params={"confirm": "DELETE"})
        )


def do_reset_password(username: str, password: str) -> None:
    with _authed_client() as client:
        user_id = _user_id(client, username)
        _check(
            client.post(
                f"/api/admin/users/{user_id}/reset-password",
                json={"password": password},
            )
        )


def do_usage(days: int = 7) -> None:
    with _authed_client() as client:
        rows = _check(client.get("/api/admin/system/usage", params={"days": days}))[
            "users"
        ]
    for row in rows:
        typer.echo(
            f"{row['username']:<20}{row['weightedTotal']:>14,.0f} "
            f"(own-key {row['ownKeyWeightedTotal']:,.0f}, {row['calls']} calls)"
        )


@admin_app.command("login")
def login_command(url: str | None = typer.Option(None, "--url")) -> None:
    do_login(
        (url or api_url()).rstrip("/"),
        typer.prompt("Username"),
        typer.prompt("Password", hide_input=True),
    )


@admin_app.command("logout")
def logout_command() -> None:
    do_logout()


@admin_app.command("whoami")
def whoami_command() -> None:
    do_whoami()


@admin_app.command("list-users")
def list_users_command() -> None:
    do_list_users()


@admin_app.command("invite")
def invite_command(expires_days: int = typer.Option(14, "--expires-days")) -> None:
    do_invite(expires_days)


@admin_app.command("set-role")
def set_role_command(username: str, role: str) -> None:
    do_set_role(username, role)


@admin_app.command("set-limits")
def set_limits_command(
    username: str,
    budget: int | None = typer.Option(None, "--budget"),
    max_jobs: int | None = typer.Option(None, "--max-jobs"),
    max_runs: int | None = typer.Option(None, "--max-runs"),
) -> None:
    do_set_limits(username, budget, max_jobs, max_runs)


@admin_app.command("usage")
def usage_command(days: int = typer.Option(7, "--days")) -> None:
    do_usage(days)


@admin_app.command("disable")
def disable_command(username: str) -> None:
    do_set_disabled(username, True)


@admin_app.command("enable")
def enable_command(username: str) -> None:
    do_set_disabled(username, False)


@admin_app.command("delete")
def delete_command(
    username: str, confirm: bool = typer.Option(False, "--confirm")
) -> None:
    if not confirm:
        raise _fail("pass --confirm to delete a user and workspace")
    do_delete(username)


@admin_app.command("reset-password")
def reset_password_command(username: str) -> None:
    password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)
    do_reset_password(username, password)
