import requests
import json

base = "http://127.0.0.1:5000"

for ep in ["/health", "/api/summary", "/api/readings", "/api/alerts", "/api/zones", "/api/history?zone_id=haldia"]:
    try:
        r = requests.get(base + ep, timeout=10)
        print(f"=== {ep} -> Status: {r.status_code} ===")
        if r.status_code == 200:
            data = r.json()
            if ep == "/api/readings":
                print(f"Readings count: {data.get('count')}")
                readings = data.get("readings", [])
                for rd in readings:
                    print(f" - {rd.get('zone_id')}: rain={rd.get('rainfall_24h_mm')}, disc={rd.get('river_discharge_m3s')}, score={rd.get('risk_score')}, level={rd.get('risk_level')}, fresh={rd.get('freshness')}")
            elif ep == "/api/summary":
                print(json.dumps(data, indent=2))
            elif ep == "/api/alerts":
                print(f"Alerts count: {data.get('count')}")
            elif ep == "/health":
                print(json.dumps(data, indent=2))
        else:
            print(f"Error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"{ep} failed: {e}")
