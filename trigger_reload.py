import requests

try:
    print("Triggering background reload...")
    res = requests.get('http://127.0.0.1:5000/reload_encodings', timeout=10)
    print(res.json())
except Exception as e:
    print("Error:", e)
