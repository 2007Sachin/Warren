"""Phase 0 acceptance test: Angel One auth + profile sanity.
Run: python tests/smoke_login.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from execution.angel_auth import login

if __name__ == "__main__":
    obj = login()
    profile = obj.getProfile(os.environ["ANGEL_CLIENT_CODE"])
    assert profile.get("status"), f"Profile fetch failed: {profile}"
    print("LOGIN OK")
    print(json.dumps(profile["data"], indent=2))
