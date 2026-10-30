import requests
payload = {"message": {"messageId": "msg-local-test-101", "role": "ROLE_USER", "parts": [{"mediaType": "application/vnd.ga5.invoice-claim-batch+json", "data": {"batchId": "batch-889911", "policyRevision": "v2.0", "packages": [{"packageId": "pkg-001", "content": "Vendor: ACME Corp. [REF-01] [REF-02]"}]}}]}}
headers = {"A2A-Version": "1.0", "Content-Type": "application/a2a+json", "Authorization": "Bearer test_token"}
try:
    r = requests.post("http://127.0.0.1:8000/a2a/message:send", headers=headers, json=payload)
    print("STATUS:", r.status_code)
    print(r.text)
except Exception as e: print("Failed:", e)
