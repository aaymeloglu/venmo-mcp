"""One-time Venmo auth script. Run with: pixi run auth"""

import json
import os
from pathlib import Path
from venmo_api import Client

TOKEN_FILE = Path(__file__).parent / ".venmo-token"


def main():
    if TOKEN_FILE.exists():
        print(f"Token already exists at {TOKEN_FILE}")
        print("Delete it first if you want to re-authenticate.")
        return

    username = input("Venmo username (email or phone without +1): ")
    password = input("Venmo password: ")

    access_token = Client.get_access_token(username=username, password=password)

    TOKEN_FILE.write_text(json.dumps({"access_token": access_token}))
    TOKEN_FILE.chmod(0o600)
    print(f"Token saved to {TOKEN_FILE}")
    print("This token never expires unless you manually revoke it.")


if __name__ == "__main__":
    main()
