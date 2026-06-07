"""Venmo MCP server for Claude Code. Run with: pixi run serve"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from venmo_api import Client, PaymentPrivacy

TOKEN_FILE = Path(__file__).parent / ".venmo-token"

mcp = FastMCP("venmo")


def _epoch_to_iso(value) -> str | None:
    """Venmo returns epoch-second strings. Format as UTC ISO (YYYY-MM-DD HH:MM:SSZ)."""
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%SZ")
    except (ValueError, TypeError, OSError):
        return str(value)


def _user_brief(user) -> dict | None:
    if not user:
        return None
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


def _serialize_txn(t, my_id) -> dict:
    """Flatten a Transaction into a JSON-friendly dict, with a direction relative to me."""
    actor_id = t.actor.id if t.actor else None
    # payment_type "pay": actor pays target. "charge": actor requests money from target.
    if t.payment_type == "charge":
        direction = "you_requested" if actor_id == my_id else "requested_from_you"
    else:  # "pay"
        direction = "sent" if actor_id == my_id else "received"
    return {
        "id": t.id,
        "date": _epoch_to_iso(t.date_created),
        "type": t.payment_type,
        "direction": direction,
        "amount": t.amount,
        "note": t.note,
        "status": t.status,
        "audience": t.audience,
        "actor": _user_brief(t.actor),
        "target": _user_brief(t.target),
    }


def get_client() -> Client:
    token = os.environ.get("VENMO_ACCESS_TOKEN")
    if not token and TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text())
        token = data.get("access_token")
    if not token:
        raise RuntimeError(
            "No Venmo access token. Run `pixi run auth` first or set VENMO_ACCESS_TOKEN."
        )
    return Client(access_token=token)


@mcp.tool()
def search_users(query: str, limit: int = 10) -> str:
    """Search for Venmo users by name or username. Use this to find a user's ID before sending/requesting money."""
    client = get_client()
    users = client.user.search_for_users(query=query, limit=limit)
    results = []
    for user in users:
        results.append(
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "profile_picture_url": user.profile_picture_url,
            }
        )
    return json.dumps(results, indent=2)


@mcp.tool()
def send_money(
    user_id: str,
    amount: float,
    note: str,
    privacy: str = "private",
    funding_source_id: str = "",
) -> str:
    """Send money to a Venmo user. Requires user_id (from search_users), amount, and a note. Privacy: private, friends, or public. Optionally specify funding_source_id from get_payment_methods."""
    client = get_client()
    privacy_map = {
        "private": PaymentPrivacy.PRIVATE,
        "friends": PaymentPrivacy.FRIENDS,
        "public": PaymentPrivacy.PUBLIC,
    }
    privacy_setting = privacy_map.get(privacy, PaymentPrivacy.PRIVATE)
    kwargs = {
        "amount": amount,
        "note": note,
        "target_user_id": int(user_id),
        "privacy_setting": privacy_setting,
    }
    if funding_source_id:
        kwargs["funding_source_id"] = funding_source_id
    success = client.payment.send_money(**kwargs)
    if success:
        return f"Sent ${amount:.2f} to user {user_id} with note: {note}"
    return "Payment failed."


@mcp.tool()
def request_money(
    user_id: str,
    amount: float,
    note: str,
    privacy: str = "private",
) -> str:
    """Request money from a Venmo user. Requires user_id (from search_users), amount, and a note. Privacy: private, friends, or public."""
    client = get_client()
    privacy_map = {
        "private": PaymentPrivacy.PRIVATE,
        "friends": PaymentPrivacy.FRIENDS,
        "public": PaymentPrivacy.PUBLIC,
    }
    privacy_setting = privacy_map.get(privacy, PaymentPrivacy.PRIVATE)
    success = client.payment.request_money(
        amount=amount,
        note=note,
        target_user_id=int(user_id),
        privacy_setting=privacy_setting,
    )
    if success:
        return f"Requested ${amount:.2f} from user {user_id} with note: {note}"
    return "Request failed."


@mcp.tool()
def get_payment_methods() -> str:
    """List available payment methods (Venmo balance, bank accounts, cards)."""
    client = get_client()
    methods = client.payment.get_payment_methods()
    results = []
    for m in methods:
        results.append({"id": m.id, "name": m.name, "role": m.role.value if m.role else None})
    return json.dumps(results, indent=2)


@mcp.tool()
def get_friends(limit: int = 50) -> str:
    """List the authenticated user's Venmo friends. Useful for finding the right user to send money to."""
    client = get_client()
    profile = client.my_profile()
    friends = client.user.get_user_friends_list(user_id=profile.id, limit=limit)
    results = []
    for f in friends:
        results.append(
            {
                "id": f.id,
                "username": f.username,
                "display_name": f.display_name,
            }
        )
    return json.dumps(results, indent=2)


@mcp.tool()
def get_transactions(
    limit: int = 20,
    with_user_id: str = "",
    note_contains: str = "",
    before_id: str = "",
) -> str:
    """List your recent Venmo transactions (payments and requests), newest first.

    Use this to check payment history — e.g. "did I already pay X?" or "find the cleaning payment".
    Each entry includes date (UTC), amount, note, status, payment type, the other party, and a
    `direction` relative to you: "sent", "received", "you_requested", or "requested_from_you".

    - with_user_id: only transactions between you and this user (from search_users/get_friends).
    - note_contains: case-insensitive substring filter on the note (applied after fetch).
    - before_id: pass a transaction id to page to older results.
    """
    client = get_client()
    my_id = client.my_profile().id
    before = before_id or None
    if with_user_id:
        page = client.user.get_transaction_between_two_users(
            user_id_one=my_id, user_id_two=with_user_id, limit=limit, before_id=before
        )
    else:
        page = client.user.get_user_transactions(
            user_id=my_id, limit=limit, before_id=before
        )
    txns = list(page) if page else []
    results = [_serialize_txn(t, my_id) for t in txns]
    if note_contains:
        needle = note_contains.lower()
        results = [r for r in results if r["note"] and needle in r["note"].lower()]
    return json.dumps(results, indent=2)


@mcp.tool()
def get_my_profile() -> str:
    """Get the authenticated user's Venmo profile."""
    client = get_client()
    profile = client.my_profile()
    return json.dumps(
        {
            "id": profile.id,
            "username": profile.username,
            "display_name": profile.display_name,
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
