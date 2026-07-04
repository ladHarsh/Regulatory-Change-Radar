import subprocess
import time
import requests

print("Starting uvicorn subprocess...")
proc = subprocess.Popen(
    ["venv\\Scripts\\uvicorn", "app.main:app", "--port", "8005"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1
)

# Wait for server to start
time.sleep(3)

print("Sending request...")
try:
    r = requests.post(
        "http://127.0.0.1:8005/api/query",
        json={"question": "What changed in the latest RBI circular?", "stream": False},
        timeout=10
    )
    print("Status code:", r.status_code)
    print("Response text:", r.text)
except Exception as e:
    print("Request failed:", e)

print("Terminating uvicorn...")
proc.terminate()
stdout, stderr = proc.communicate(timeout=5)

print("\n--- STDOUT ---")
print(stdout)
print("\n--- STDERR ---")
print(stderr)
