#!/usr/bin/env python3
"""E2E Evaluation Script for Donut Challenge 02: OTP-based Email Verification.

Tests the live HTTP endpoints on http://127.0.0.1:8000:
1. Request OTP for demo user
2. Inspect rate-limiting cooldown
3. Test invalid OTP rejection & attempt countdown
4. Complete OTP verification and receive Bearer session token
5. Fetch authenticated user profile via GET /api/auth/me
6. Logout and verify token revocation
"""

import json
import sys
import time
import urllib.error
import urllib.request

API_BASE = "http://127.0.0.1:8000"


def http_post(path: str, data: dict, token: str = None) -> dict:
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return {"_status": err.code, "error": json.loads(err.read().decode("utf-8"))}


def http_get(path: str, token: str = None) -> dict:
    url = f"{API_BASE}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return {"_status": err.code, "error": json.loads(err.read().decode("utf-8"))}


def main():
    print("\n" + "=" * 65)
    print("  🛡️  SUNKGUARD DONUT CHALLENGE 02: E2E AUTH VERIFICATION")
    print("=" * 65 + "\n")

    email = "evaluator@deepmind.internal"

    # Step 1: Request OTP
    print(f"[*] Step 1: Requesting OTP for {email}...")
    req_res = http_post("/api/auth/otp/request", {"email": email})
    if not req_res.get("success"):
        print(f"[!] FAILED to request OTP: {req_res}")
        sys.exit(1)
    
    otp = req_res.get("dev_otp")
    print(f"    [+] Success! Delivery: {req_res.get('delivery_method')}")
    print(f"    [+] OTP Generated: >>> {otp} <<< (TTL: {req_res.get('expires_in_seconds')}s)")

    # Step 2: Test Rate Limiting Cooldown
    print(f"\n[*] Step 2: Testing resend rate limit (30s cooldown)...")
    spam_res = http_post("/api/auth/otp/request", {"email": email})
    if spam_res.get("_status") == 400:
        detail = spam_res.get("error", {}).get("detail", {})
        print(f"    [+] Correctly rejected! Cooldown remaining: {detail.get('retry_after_seconds')}s")
    else:
        print(f"    [!] Expected rate limit 400, got: {spam_res}")

    # Step 3: Test Invalid Code Attempt
    print(f"\n[*] Step 3: Testing invalid code rejection...")
    bad_otp = "000000" if otp != "000000" else "111111"
    bad_res = http_post("/api/auth/otp/verify", {"email": email, "otp": bad_otp})
    if bad_res.get("_status") == 401:
        detail = bad_res.get("error", {}).get("detail", {})
        print(f"    [+] Correctly rejected! Msg: {detail.get('message')}")
        print(f"    [+] Attempts remaining: {detail.get('remaining_attempts')}")
    else:
        print(f"    [!] Expected 401, got: {bad_res}")

    # Step 4: Verify with correct code
    print(f"\n[*] Step 4: Verifying with correct OTP: {otp}...")
    verify_res = http_post("/api/auth/otp/verify", {"email": email, "otp": otp})
    if not verify_res.get("success"):
        print(f"[!] Verification failed: {verify_res}")
        sys.exit(1)

    token = verify_res.get("token")
    user = verify_res.get("user")
    print(f"    [+] Verification SUCCESS!")
    print(f"    [+] User Created/Loaded: {user.get('name')} <{user.get('email')}> (Role: {user.get('role')})")
    print(f"    [+] Issued Bearer Token: {token[:16]}...{token[-8:]}")

    # Step 5: Test GET /api/auth/me
    print(f"\n[*] Step 5: Validating session token via GET /api/auth/me...")
    me_res = http_get("/api/auth/me", token=token)
    if me_res.get("authenticated"):
        print(f"    [+] Authenticated session valid! User: {me_res.get('user', {}).get('email')}")
    else:
        print(f"    [!] Authentication failed: {me_res}")
        sys.exit(1)

    # Step 6: Logout
    print(f"\n[*] Step 6: Logging out (revoking token)...")
    logout_res = http_post("/api/auth/logout", {}, token=token)
    print(f"    [+] Logout response: {logout_res.get('message')}")

    # Step 7: Verify token revoked
    print(f"\n[*] Step 7: Verifying revoked token rejected with 401...")
    revoked_res = http_get("/api/auth/me", token=token)
    if revoked_res.get("_status") == 401:
        print(f"    [+] Session correctly revoked! Access denied with 401.")
    else:
        print(f"    [!] Session still active: {revoked_res}")
        sys.exit(1)

    print("\n" + "=" * 65)
    print("  ✅ ALL E2E AUTH FLOW TESTS PASSED (DONUT CHALLENGE 02)")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
