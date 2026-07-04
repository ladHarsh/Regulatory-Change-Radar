import httpx

url = "https://regulatory-change-radar-backend.onrender.com/api/query"

print("--- Sending OPTIONS request (Preflight) ---")
headers = {
    "Origin": "https://regulatory-change-radar.vercel.app",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}
resp = httpx.options(url, headers=headers)
print(f"Status: {resp.status_code}")
for k, v in resp.headers.items():
    print(f"{k}: {v}")

print("\n--- Sending POST request ---")
resp_post = httpx.post(url, json={"question": "test"}, headers={"Origin": "https://regulatory-change-radar.vercel.app"})
print(f"Status: {resp_post.status_code}")
for k, v in resp_post.headers.items():
    print(f"{k}: {v}")
print(resp_post.text[:300])
