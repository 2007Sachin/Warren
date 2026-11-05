"""Angel One SmartAPI authentication: TOTP login + token lifecycle.

Tokens expire every morning (regulatory daily logout). Run this at ~07:30 IST
on the VPS via cron; tokens are written to a JSON file other modules read.
"""
import os, json, logging
from datetime import date
import pyotp
from SmartApi import SmartConnect

log = logging.getLogger("angel_auth")
TOKEN_FILE = os.environ.get("ANGEL_TOKEN_FILE", "data/store/session.json")


def login() -> SmartConnect:
    api_key = os.environ["ANGEL_API_KEY"]
    totp = pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now()
    obj = SmartConnect(api_key=api_key)
    resp = obj.generateSession(os.environ["ANGEL_CLIENT_CODE"], os.environ["ANGEL_PIN"], totp)
    if not resp.get("status"):
        raise RuntimeError(f"SmartAPI login failed: {resp}")
    data = resp["data"]
    session = {
        "jwtToken": data["jwtToken"],
        "refreshToken": data["refreshToken"],
        "feedToken": data["feedToken"],
        "date": str(date.today()),
    }
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(session, f)
    log.info("Login OK, tokens cached to %s", TOKEN_FILE)
    return obj


def get_session() -> SmartConnect:
    """Return an authenticated SmartConnect; re-login if today's token is missing."""
    try:
        with open(TOKEN_FILE) as f:
            session = json.load(f)
        if session["date"] == str(date.today()):
            obj = SmartConnect(api_key=os.environ["ANGEL_API_KEY"])
            obj.setAccessToken(session["jwtToken"])
            obj.setRefreshToken(session["refreshToken"])
            obj.setFeedToken(session["feedToken"])
            return obj
    except FileNotFoundError:
        pass
    return login()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    obj = login()
    profile = obj.getProfile(os.environ["ANGEL_CLIENT_CODE"])
    print(json.dumps(profile, indent=2))
