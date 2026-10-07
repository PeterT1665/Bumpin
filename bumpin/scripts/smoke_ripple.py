"""End-to-end check: approving a ripple action must move the schedule,
draft exactly one email, and send nothing."""
import json
import urllib.error
import urllib.request

B = "http://localhost:8000/api"


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        B + path, data=data, method=method,
        headers={"Content-Type": "application/json", "X-User": "ravi"},
    )
    try:
        return json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, "body": json.loads(e.read().decode() or "{}")}


def nova():
    for r in call("/runsheet"):
        if r["who"] == "Nova Lane":
            return r
    return None


def dusk():
    for r in call("/runsheet"):
        if r["who"] == "Dusk Theory":
            return r
    return None


print("BEFORE  Nova Lane :", nova()["start"], "->", nova()["end"])
print("BEFORE  Dusk Theory:", dusk()["start"], "->", dusk()["end"])
print("BEFORE  outbox    :", len(call("/outbox")), "rows")

t = call("/tickets/7")
print("\nticket 7:", t["type"], "/", t["status"])
for a in t["proposed_actions"]:
    print(f'  [{a["index"]}] {a["status"]:<9}{a["title"]}')

print("\n--- approve action 0 ---")
r = call("/tickets/7/actions/0/approve", "POST")
if "HTTP" in r:
    print("REFUSED", r["HTTP"], r["body"])
else:
    print("ticket status now:", r["status"])
    for a in r["proposed_actions"]:
        print(f'  [{a["index"]}] {a["status"]:<9}{a["title"]}  outbox={a.get("outbox_id")}')

print("\nAFTER   Nova Lane :", nova()["start"], "->", nova()["end"])
print("AFTER   Dusk Theory:", dusk()["start"], "->", dusk()["end"])
ob = call("/outbox")
print("AFTER   outbox    :", len(ob), "rows")
for o in ob:
    print(f'   [{o["status"]:<5}] -> {o["to_addr"]:<36}{o["subject"][:46]}')
sent = [o for o in ob if o["status"] == "sent"]
print("\nSENT COUNT (must be 0):", len(sent))
