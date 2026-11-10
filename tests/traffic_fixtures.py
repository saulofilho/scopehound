import base64
import json

JUICE = "http://app.lab"


def har_entry(
    method,
    url,
    *,
    status=200,
    body="",
    req_body="",
    ctype="application/json",
    req_ctype="application/json",
    b64=False,
    cookie="",
):
    headers = [{"name": "Content-Type", "value": req_ctype}] if req_body else []
    if cookie:
        headers.append({"name": "Cookie", "value": cookie})
    content = {"mimeType": ctype, "text": body}
    if b64:
        content = {
            "mimeType": ctype,
            "encoding": "base64",
            "text": base64.b64encode(body.encode()).decode(),
        }
    return {
        "startedDateTime": "2026-11-10T10:00:00Z",
        "time": 12.5,
        "request": {
            "method": method,
            "url": url,
            "headers": headers,
            **({"postData": {"mimeType": req_ctype, "text": req_body}} if req_body else {}),
        },
        "response": {
            "status": status,
            "headers": [{"name": "Content-Type", "value": ctype}],
            "content": content,
        },
    }


def juice_har() -> str:
    entries = [
        har_entry("GET", f"{JUICE}/rest/products/search?q=apple", body='[{"id":1}]'),
        har_entry("GET", f"{JUICE}/api/Products/1", body='{"id":1,"name":"Apple"}'),
        har_entry("GET", f"{JUICE}/api/Products/24", body='{"id":24}', b64=True),
        har_entry(
            "GET",
            f"{JUICE}/rest/basket/6",
            body='{"id":6,"UserId":21}',
            cookie="token=abc; language=en",
        ),
        har_entry(
            "POST",
            f"{JUICE}/api/BasketItems",
            req_body='{"ProductId":1,"BasketId":"6","quantity":1}',
            status=201,
        ),
        har_entry(
            "POST",
            f"{JUICE}/rest/user/login",
            req_body='{"email":"a@lab","password":"x"}',
            status=401,
        ),
        har_entry("GET", f"{JUICE}/api/Users/a3f1c2d4-1111-2222-3333-444455556666", status=401),
        har_entry("GET", "http://evil.com/track?id=1"),  # fora do escopo
        har_entry("GET", f"{JUICE}/logout"),  # excluído
        har_entry("GET", f"{JUICE}/socket.io/?EIO=4", status=0),  # sem resposta
    ]
    return json.dumps({"log": {"version": "1.2", "entries": entries}})


def _b64(raw: str) -> str:
    return base64.b64encode(raw.encode()).decode()


def burp_xml() -> str:
    request = "GET /api/Users/3 HTTP/1.1\r\nHost: app.lab\r\nAuthorization: Bearer t\r\n\r\n"
    response = 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{"id":3,"role":"admin"}'
    post = (
        "POST /api/Feedbacks HTTP/1.1\r\nHost: app.lab\r\nContent-Type: "
        "application/x-www-form-urlencoded\r\n\r\nUserId=3&rating=5"
    )
    return f"""<?xml version="1.0"?>
<!DOCTYPE items [
<!ELEMENT items (item*)>
<!ATTLIST items burpVersion CDATA "">
]>
<items burpVersion="2026.10">
  <item>
    <time>Tue Nov 10 10:00:00 BRT 2026</time>
    <url><![CDATA[http://app.lab/api/Users/3]]></url>
    <host ip="10.0.0.5">app.lab</host><port>80</port><protocol>http</protocol>
    <method><![CDATA[GET]]></method><path><![CDATA[/api/Users/3]]></path>
    <request base64="true"><![CDATA[{_b64(request)}]]></request>
    <status>200</status><responselength>24</responselength><mimetype>JSON</mimetype>
    <response base64="true"><![CDATA[{_b64(response)}]]></response>
    <comment></comment>
  </item>
  <item>
    <url><![CDATA[http://app.lab/api/Feedbacks]]></url>
    <method><![CDATA[POST]]></method>
    <request base64="true"><![CDATA[{_b64(post)}]]></request>
    <response base64="true"></response>
  </item>
</items>"""


XXE = """<?xml version="1.0"?>
<!DOCTYPE items [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<items><item><url>http://app.lab/&xxe;</url></item></items>"""
