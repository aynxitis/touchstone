"""Token-free security checks (needs network). Run: .venv/bin/python test_security.py"""
import ipaddress
import socket
import time

import fetch_links as F

# 1. DNS rebinding: a host that resolves public on the check and to 127.0.0.1 afterwards
#    must be fetched from the checked IP, with exactly one DNS lookup.
public_ip = socket.getaddrinfo("example.com", 80, type=socket.SOCK_STREAM)[0][4][0]
real_getaddrinfo, lookups, peers = socket.getaddrinfo, [], []


def rebinding(host, *a, **k):
    if host == "rebind.example":
        lookups.append(host)
        ip = public_ip if len(lookups) == 1 else "127.0.0.1"
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 80))]
    return real_getaddrinfo(host, *a, **k)


real_peer_ok = F.peer_ok


def spy(r):
    stream = r.extensions.get("network_stream")
    peers.append(stream.get_extra_info("server_addr")[0] if stream else None)
    return real_peer_ok(r)


socket.getaddrinfo, F.peer_ok = rebinding, spy
F.fetch("http://rebind.example/path?q=1")
socket.getaddrinfo, F.peer_ok = real_getaddrinfo, real_peer_ok
assert lookups == ["rebind.example"] and peers == [public_ip], (lookups, peers)

# 2. TLS is still verified against the hostname, not the pinned IP: 8.8.8.8's certificate
#    covers the IP 8.8.8.8 but not example.com, so this must fail.
real_check = F.check_url


async def wrong_ip(url):
    return True, "", ipaddress.ip_address("8.8.8.8")


F.check_url = wrong_ip
assert F.fetch("https://example.com/")["status"] == "ERROR"
F.check_url = real_check

# 3. Private targets stay blocked, directly and through redirects or IPv6 forms.
for url in ("http://127.0.0.1/", "http://[::ffff:127.0.0.1]/", "http://10.0.0.1/",
            "http://httpbin.org/redirect-to?url=http://169.254.169.254/"):
    assert F.fetch(url)["status"] == "BLOCKED", url

# 4. Client IP: only the configured header counts, junk falls back, tables get pruned.
import app as A

A.CLIENT_IP_HEADER = "True-Client-IP"
from starlette.datastructures import Headers

Req = lambda h, peer="10.0.0.5": type("R", (), {"headers": Headers(h), "client": type("C", (), {"host": peer})})()
assert A.client_ip(Req({"true-client-ip": "203.0.113.7", "x-forwarded-for": "1.2.3.4"})) == "203.0.113.7"
assert A.client_ip(Req({"true-client-ip": "<script>"})) == "10.0.0.5"
A.CLIENT_IP_HEADER = ""
assert A.client_ip(Req({"true-client-ip": "203.0.113.7"})) == "10.0.0.5"
A.hits["198.51.100.1"].append(time.time() - 4000)
A.last_prune = time.time() - A.PRUNE_EVERY - 1
A.rate_limited("192.0.2.1")
assert "198.51.100.1" not in A.hits and "192.0.2.1" in A.hits

# 5. IPv6: one /64 is one visitor, so rotating addresses inside it doesn't reset the limit.
assert A.rate_key("2001:db8:abcd:12::1") == A.rate_key("2001:db8:abcd:12::ffff") == "2001:db8:abcd:12::/64"
assert A.rate_key("2001:db8:abcd:13::1") != A.rate_key("2001:db8:abcd:12::1")
assert A.rate_key("::ffff:203.0.113.7") == "203.0.113.7"

# 6. Daily cap: full at GLOBAL_AUDITS_PER_DAY, and a new UTC day starts from zero.
A.daily.update(day=A.utc_today(), count=A.DAILY_LIMIT)
assert A.daily_used_up()
A.daily.update(day=A.utc_today() - __import__("datetime").timedelta(days=1))
assert not A.daily_used_up() and A.daily["count"] == 0

# 7. Fail-closed accounting: an audit counts at its first model call attempt, even if the
#    call fails or reports no tokens; an audit that never calls the model doesn't count.
A.daily.update(day=A.utc_today(), count=0)
def failing(**k): raise TimeoutError("timed out")
wrapped = A.CountingClient(__import__("types").SimpleNamespace(
    chat=__import__("types").SimpleNamespace(completions=__import__("types").SimpleNamespace(create=failing))))
for _ in range(3):
    try: wrapped.chat.completions.create(model="x")
    except TimeoutError: pass
assert A.daily["count"] == 1
A.CountingClient(None)
assert A.daily["count"] == 1

print("security checks passed")
