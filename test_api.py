import requests

url = "http://127.0.0.1:5000/health"
r = requests.get(url)

print("Status:", r.status_code)
try:
    print("Response:", r.json())
except Exception as e:
    print("JSON decode error:", e)
    print("Raw text:", r.text)
