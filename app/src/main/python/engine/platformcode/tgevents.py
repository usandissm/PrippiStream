# -*- coding: utf-8 -*-
"""TheGroove live football events ("Eventi Calcio" home row).

Fetches the Mr_Dupont Sport_Calcio.xml scripter page from TheGroove360 using
the addon's exact token protocol (see plugin.video.thegroove360):

  - token = base64url(f"{ts}.{digitcount}{idx}{random}") with idx = ts % len(item_parser lines)
  - GET https://thegroove360.org/loader.php?page=<composed>&token=<token>
  - response header "Thegroove" must equal the token exactly
  - body is base64url of AES-256-CFB8 ciphertext:
      key = line[idx] of item_parser.py, stripped, right-padded/truncated to 32 bytes
      iv  = sha256(key).hexdigest()[:16] as ASCII bytes

The decrypted page is NOT pure XML (it starts with PHP headers), so events are
extracted with tolerant regexes: a match event is a <title> of the form
"HH:MM - Team A vs Team B (League)" followed by its link/sublink block.

Sources: HLS (.m3u8) links first, then plain web/HTTP as fallback. AceStream
links are ignored on purpose (no acestream infra in this addon).
"""
import base64
import hashlib
import json
import os
import random
import re
import time
from datetime import date, timedelta

SERVER = 'https://thegroove360.org/'
DEFAULT_PAGE = '/thegroove/scripters/Mr_Dupont/path=Sport_Calcio.xml'
_CACHE_NAME = 'tg_events_cache.json'
_CACHE_TTL = 3 * 3600          # home row shows cached events for up to 3 h

# Server-side per-page request cooldown (~5 min, same order as the 375 s key
# rotation): requests inside this window answer Content-Length: 0. Both the
# background cycle and on-demand click refreshes stay outside it.
FETCH_COOLDOWN_S = 12 * 60

# Fallback browser UAs (used when the installed TheGroove addon's UA.json is
# not readable, e.g. standalone tests).
_UA_FALLBACK = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.1',
)

# Embedded copy of TheGroove's item_parser.py key pool (base64). Used only when
# the installed addon cannot be located; at runtime the live file wins so key
# rotations propagate automatically.
_ITEM_PARSER_B64 = 'aW1wb3J0IGxvZ2dpbmcKaW1wb3J0IHhibWNhZGRvbgppbXBvcnQgcmUKCmZyb20gcmVzb3VyY2VzLmxpYiBpbXBvcnQga29kaWxvZ2dpbmcKZnJvbSByZXNvdXJjZXMubW9kdWxlcy50aGVncm9vdmUudGhlZ3Jvb3ZlX2l0ZW0gaW1wb3J0IFRoZWdyb292ZUl0ZW0KZnJvbSByZXNvdXJjZXMubW9kdWxlcy50aGVncm9vdmUudGhlZ3Jvb3ZlX3JlZ2V4ZXMgaW1wb3J0IFRoZWdyb292ZVJlZ2V4ZXMKZnJvbSByZXNvdXJjZXMubW9kdWxlcy5odHRwY2xpZW50IGltcG9ydCBIdHRwQ2xpZW50CmZyb20gcmVzb3VyY2VzLmxpYiBpbXBvcnQga29kaXV0aWxzCgppbXBvcnQgcmVzb3VyY2VzLm1vZHVsZXMudGhlZ3Jvb3ZlLnRtZGJfd3JhcHBlciBhcyB0bWRiYXBpCgp0cnk6CiAgICBpbXBvcnQgcXVldWUgYXMgbVF1ZXVlCmV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgIGltcG9ydCBRdWV1ZSBhcyBtUXVldWUKCmZyb20gcmVzb3VyY2VzLm1vZHVsZXMudGhlZ3Jvb3ZlIGltcG9ydCBzdXBwb3J0CgpBRERPTiA9IHhibWNhZGRvbi5BZGRvbigpCmxvZ2dlciA9IGxvZ2dpbmcuZ2V0TG9nZ2VyKEFERE9OLmdldEFkZG9uSW5mbygnaWQnKSkKa29kaWxvZ2dpbmcuY29uZmlnKCkKCgpjbGFzcyBJdGVtUGFyc2VyOgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzZWxmLnBhZ2VfbGlzdCA9IG1RdWV1ZS5RdWV1ZSgpCiAgICAgICAgc2VsZi5yZWdleF9tb2RlID0gTm9uZQogICAgICAgIHNlbGYucmVwZWF0X21vZGUgPSBOb25lCgogICAgZGVmIHBhcnNlX3BhZ2Uoc2VsZiwgeG1sKToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGxvZ2dlci5kZWJ1ZygiX19fX19fIHBhcnNlIHBhZ2UgX19fX19fIikKICAgICAgICAgICAgcmVnZXggPSByJyg8aXRlbT4oPzouKj8pPC9pdGVtPnw8ZGlyPig/Oi4qPyk8L2Rpcj58PHBsdWdpbj4oPzouKj8pPC9wbHVnaW4+KScKICAgICAgICAgICAgbWF0Y2hlcyA9IHJlLmNvbXBpbGUocmVnZXgsIHJlLk1VTFRJTElORSB8IHJlLlMpLmZpbmRhbGwoeG1sKQogICAgICAgICAgICAjIHF1ZXVlID0gbVF1ZXVlLlF1ZXVlKCkKICAgICAgICAgICAgZm9yIG1hdGNoIGluIG1hdGNoZXM6CiAgICAgICAgICAgICAgICBzZWxmLnBhZ2VfbGlzdC5wdXQobWF0Y2gpCgogICAgICAgICAgICBzZWxmLnBhcnNlX2l0ZW1fbXQoc2VsZi5wYWdlX2xpc3QsIHVzZV9sb2NrPVRydWUpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgcmFpc2UgZQoKICAgIGRlZiBwYXJzZV9pdGVtKHNlbGYsIHhtbF9pdGVtLCBwYXJlbnRfeG1sPSIiLCByZWdleGVzPU5vbmUpOgogICAgICAgIGxvZ2dlci5kZWJ1ZygiX19fX19fX19fX19fIFBBUlNFIElURU0gX19fX19fX19fX19fX18iKQoKICAgICAgICAjIGxvZ2dlci5kZWJ1Zyh4bWxfaXRlbSkKCiAgICAgICAgbGkgPSBUaGVncm9vdmVJdGVtKCkKICAgICAgICBpZiByZWdleGVzOgogICAgICAgICAgICAjIGxpLnJlZ2V4ZXMuYXBwZW5kKHJlZ2V4ZXMpCiAgICAgICAgICAgIGZvciByZXggaW4gcmVnZXhlczoKICAgICAgICAgICAgICAgIGlmIHR5cGUocmV4KSA9PSBkaWN0OgogICAgICAgICAgICAgICAgICAgIHJleCA9IFRoZWdyb292ZVJlZ2V4ZXMuZGljdF90b19vYmoocmV4KQogICAgICAgICAgICAgICAgbGkucmVnZXhlcy5hcHBlbmQocmV4KQoKICAgICAgICBsaS5wYXJlbnRfeG1sID0gcGFyZW50X3htbAogICAgICAgIGxpLl9yYXcgPSB4bWxfaXRlbQoKICAgICAgICB4bWxfc3RyaXBwZWQgPSByZS5zdWIociI8cmVnZXg+KC4qPyk8L3JlZ2V4PiIsICIiLCB4bWxfaXRlbSwgMCwgcmUuTVVMVElMSU5FIHwgcmUuRE9UQUxMKQoKICAgICAgICBtZXRhID0gcmUuY29tcGlsZShyJzxtZXRhPiguKj8pPC9tZXRhPicsIHJlLlMpLmZpbmRhbGwoeG1sX3N0cmlwcGVkKQoKICAgICAgICB4bWxfc3RyaXBwZWQgPSByZS5zdWIociI8bWV0YT4oLio/KTwvbWV0YT4iLCAiIiwgeG1sX3N0cmlwcGVkLCAwLCByZS5TKQoKICAgICAgICBtYXRjaGVzID0gcmUuY29tcGlsZShyJzwoW14vPl0rKT4nLCByZS5NVUxUSUxJTkUpLmZpbmRhbGwoeG1sX3N0cmlwcGVkKQoKICAgICAgICAjIGxvZ2dlci5kZWJ1ZyhtYXRjaGVzKQoKICAgICAgICBmb3IgdGFnIGluIG1hdGNoZXM6CiAgICAgICAgICAgIGNsb3N1cmUgPSB0YWcuc3BsaXQoIiAiKVswXQogICAgICAgICAgICByZWdleCA9ICc8JyArIHRhZyArICc+KC4qPyk8LycgKyBjbG9zdXJlICsgJz4nCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHZhbHVlID0gcmUuY29tcGlsZShyZWdleCwgcmUuUykuZmluZGFsbCh4bWxfc3RyaXBwZWQpWzBdCiAgICAgICAgICAgIGV4Y2VwdDoKICAgICAgICAgICAgICAgIHZhbHVlID0gIiIKCiAgICAgICAgICAgICMgbG9nZ2VyLmRlYnVnKHZhbHVlKQogICAgICAgICAgICBpZiB0YWcgPT0gIm5hbWUiIG9yIHRhZyA9PSAidGl0bGUiOgogICAgICAgICAgICAgICAgbGkubGFiZWwgPSB2YWx1ZSAgIyB1Jycuam9pbih2YWx1ZSkuZW5jb2RlKCJ1dGYtOCIpLnN0cmlwKCkKCiAgICAgICAgICAgIGlmIHRhZy5zdGFydHN3aXRoKCJsaW5rIik6CiAgICAgICAgICAgICAgICBmcm9tIHJlc291cmNlcy5tb2R1bGVzLnRoZWdyb292ZS50aGVncm9vdmVfaHR0cGNsaWVudCBpbXBvcnQgVGhlZ3Jvb3ZlSHR0cENsaWVudCBhcyBUR0NsaWVudAogICAgICAgICAgICAgICAgdGdfY2xpID0gVEdDbGllbnQoKQogICAgICAgICAgICAgICAgaWYgdmFsdWUuc3RyaXAoKS5zdGFydHN3aXRoKCIvdGhlZ3Jvb3ZlLyIpIG9yIHZhbHVlLnN0cmlwKCkuc3RhcnRzd2l0aCh0Z19jbGkuc2VydmVyX3VybCk6CiAgICAgICAgICAgICAgICAgICAgaXNfdGhlZ3Jvb3ZlX2xpbmsgPSBUcnVlCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIGlzX3RoZWdyb292ZV9saW5rID0gRmFsc2UKCiAgICAgICAgICAgICAgICBpZiBpc190aGVncm9vdmVfbGluayBvciB2YWx1ZS5zdHJpcCgpLnN0YXJ0c3dpdGgoIiRkb3JlZ2V4WyIpOgogICAgICAgICAgICAgICAgICAgIGxpLnVybCA9IHZhbHVlCgogICAgICAgICAgICAgICAgICAgIHJ4bWwgPSBsaS5wYXJlbnRfeG1sIGlmIGxpLnBhcmVudF94bWwgIT0gIiIgZWxzZSBsaS5fcmF3CiAgICAgICAgICAgICAgICAgICAgaXNfcmVwZWF0X3JlZ2V4ID0gSXRlbVBhcnNlci5pc19yZXBlYXRfcmVnZXgodmFsdWUsIHJ4bWwpCgogICAgICAgICAgICAgICAgICAgIGlmIGlzX3RoZWdyb292ZV9saW5rIG9yIGlzX3JlcGVhdF9yZWdleDoKICAgICAgICAgICAgICAgICAgICAgICAgbGkuaXNfZm9sZGVyID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgICAgIGxpLmlzX2ZvbGRlciA9IEZhbHNlCiAgICAgICAgICAgICAgICAgICAgICAgIGxpLmlzX3BsYXlhYmxlID0gVHJ1ZQoKICAgICAgICAgICAgICAgIGVsaWYgIjxzdWJsaW5rIiBpbiB2YWx1ZToKICAgICAgICAgICAgICAgICAgICBzdWJscyA9IHJlLmNvbXBpbGUocicoPHN1YmxpbmsoLio/KT4oLio/KTwvc3VibGluaz4pJywgcmUuTVVMVElMSU5FKS5maW5kYWxsKHZhbHVlKQogICAgICAgICAgICAgICAgICAgIHJlc29sdmVyX3R5cGUgPSAiIgogICAgICAgICAgICAgICAgICAgIGZvciBzdWJ4bWwsIHN1YnBhciwgc3VibCBpbiBzdWJsczoKICAgICAgICAgICAgICAgICAgICAgICAgbmFtZSA9ICIiCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIHN1YnBhcjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBuYW1lID0gcmUuY29tcGlsZShyJ25hbWU9XCIoW15cIl0rKVwiJywgcmUuTVVMVElMSU5FIHwgcmUuRE9UQUxMKS5maW5kYWxsKHN1YnBhcilbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBuYW1lID0gIiIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJlc29sdmVyX3R5cGUgPSBUaGVncm9vdmVJdGVtLmdldF90aGVncm9vdmVfcmVzb2x2ZXIoc3VieG1sLCBzdWJsKQogICAgICAgICAgICAgICAgICAgICAgICBsaS5zdWJsaW5rcy5hcHBlbmQoKG5hbWUsIHN1YmwsIHJlc29sdmVyX3R5cGUpKQogICAgICAgICAgICAgICAgICAgIGxpLmlzX2ZvbGRlciA9IEZhbHNlCiAgICAgICAgICAgICAgICAgICAgbGkudXJsID0gIiIKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgIyBsb2dnZXIuZGVidWcoIkVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUUiKQogICAgICAgICAgICAgICAgICAgIGxpLnRnX3Jlc29sdmVyID0gVGhlZ3Jvb3ZlSXRlbS5nZXRfdGhlZ3Jvb3ZlX3Jlc29sdmVyKHRhZywgdmFsdWUpCiAgICAgICAgICAgICAgICAgICAgIyBsb2dnZXIuZGVidWcobGkudGdfcmVzb2x2ZXIpCiAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBpc191cmwgPSAodmFsdWUuaW5kZXgoIjovLyIpIG9yICh2YWx1ZS5zdGFydHN3aXRoKCJwbHVnaW4iKSBvciB2YWx1ZS5zdGFydHN3aXRoKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgImh0dHAiKSkgb3IgbGkudGdfcmVzb2x2ZXIgIT0gIiIpID49IDAKICAgICAgICAgICAgICAgICAgICAgICAgaWYgaXNfdXJsOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgbGkuaXNfZm9sZGVyID0gRmFsc2UKCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiB2YWx1ZS5zdGFydHN3aXRoKCJodHRwIik6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgbGkudGdfcmVzb2x2ZXIgPT0gImV4dHNyYyI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGxpLmlzX2ZvbGRlciA9IFRydWUKCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBsaS51cmwgPSB2YWx1ZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0OgogICAgICAgICAgICAgICAgICAgICAgICBpZiBsaS50Z19yZXNvbHZlciA9PSAiIiBvciBub3QgbGkudGdfcmVzb2x2ZXI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBsaS5pc19mb2xkZXIgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBsaS51cmwgPSB2YWx1ZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBsaS5pc19mb2xkZXIgPSBGYWxzZQoKICAgICAgICAgICAgaWYgdGFnID09ICJ0aHVtYm5haWwiOgogICAgICAgICAgICAgICAgbGkuYXJ0c1sidGh1bWIiXSA9IHZhbHVlCgogICAgICAgICAgICBpZiB0YWcgPT0gImZhbmFydCI6CiAgICAgICAgICAgICAgICBsaS5hcnRzWyJmYW5hcnQiXSA9IHZhbHVlCgogICAgICAgICAgICBpZiB0YWcgPT0gInBsb3QiOgogICAgICAgICAgICAgICAgbGkuaW5mb1sicGxvdCJdID0gdmFsdWUgICMgdScnLmpvaW4odmFsdWUpLmVuY29kZSgidXRmLTgiKS5zdHJpcCgpLmRlY29kZSgidXRmLTgiLCAiaWdub3JlIikKCiAgICAgICAgaWYgeG1sX2l0ZW0uc3RhcnRzd2l0aCgiPHBsdWdpbj4iKToKICAgICAgICAgICAgbGkuaXNfZm9sZGVyID0gRmFsc2UKICAgICAgICAgICAgbGkuaXNfcGx1Z2luID0gVHJ1ZQoKICAgICAgICBpZiBtZXRhOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiAibWFrZWxpc3QiIG5vdCBpbiBtZXRhIGFuZCBrb2RpdXRpbHMuZ2V0X3NldHRpbmdfYXNfYm9vbCgiaXNfdG1kYiIpOgogICAgICAgICAgICAgICAgICAgIGxpID0gdG1kYmFwaS50bWRiKG1ldGFbMF0sIGxpKQogICAgICAgICAgICBleGNlcHQ6CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgIGZyb20gcmVzb3VyY2VzLmxpYiBpbXBvcnQgcGx1Z2luCiAgICAgICAgcGx1Z2luLnNob3dfaXRlbShsaSkKICAgICAgICAjIHNlbGYucGFnZV9saXN0LmFwcGVuZChsaSkKCiAgICBkZWYgcGFyc2VfcmVnZXgoc2VsZiwgaXRlbSk6CiAgICAgICAgbG9nZ2VyLmRlYnVnKCJfX19fX19fX18gUEFSU0UgUkVHRVggX19fX19fX19fX18iKQogICAgICAgICMgcmVnZXhfbmFtZSA9IHJlLmNvbXBpbGUocic8bGluaz5cJGRvcmVnZXhcWyguKj8pXF08L2xpbms+JywgcmUuTVVMVElMSU5FKS5maW5kYWxsKHhtbF9pdGVtKVswXQogICAgICAgIHJlZ2V4X25hbWUgPSByZS5jb21waWxlKHInXCRkb3JlZ2V4XFsoLio/KVxdJywgcmUuTVVMVElMSU5FKS5maW5kYWxsKGl0ZW0udXJsKVswXQoKICAgICAgICAjIGxvZ2dlci5kZWJ1ZyhyZWdleF9uYW1lKQogICAgICAgICMgbG9nZ2VyLmRlYnVnKGl0ZW0ucGFyYW1zKQoKICAgICAgICB4bWxfaXRlbSA9IGl0ZW0uX3JhdyBpZiBpdGVtLnBhcmVudF94bWwgPT0gIiIgZWxzZSBpdGVtLnBhcmVudF94bWwKCiAgICAgICAgIyBsb2dnZXIuZGVidWcoeG1sX2l0ZW0pCgogICAgICAgIHJlZ2V4ID0gcic8cmVnZXg+KFxzKzxuYW1lPicgKyByZWdleF9uYW1lICsgJzwvbmFtZT4uKj8pPC9yZWdleD4nCiAgICAgICAgcmVnZXhfdGFnID0gcmUuY29tcGlsZShyZWdleCwgcmUuRE9UQUxMKS5maW5kYWxsKHhtbF9pdGVtKVswXQoKICAgICAgICAjIGxvZ2dlci5kZWJ1ZyhyZWdleF90YWcpCgogICAgICAgIHRyeToKICAgICAgICAgICAgbGlzdHJlcGVhdCA9IHJlLmNvbXBpbGUocic8bGlzdHJlcGVhdD4oLio/KTwvbGlzdHJlcGVhdD4nLCByZS5ET1RBTEwpLmZpbmRhbGwocmVnZXhfdGFnKVswXQogICAgICAgICAgICAjIGxvZ2dlci5kZWJ1ZyhsaXN0cmVwZWF0KQogICAgICAgIGV4Y2VwdDoKICAgICAgICAgICAgbGlzdHJlcGVhdCA9ICIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICBleHByZXMgPSByZS5jb21waWxlKHInPGV4cHJlcz4oLio/KTwvZXhwcmVzPicsIHJlLkRPVEFMTCkuZmluZGFsbChyZWdleF90YWcpWzBdCiAgICAgICAgICAgICMgbG9nZ2VyLmRlYnVnKGV4cHJlcykKICAgICAgICBleGNlcHQ6CiAgICAgICAgICAgIGV4cHJlcyA9ICIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICBwYWdlID0gcmUuY29tcGlsZShyJzxwYWdlPiguKj8pPC9wYWdlPicsIHJlLkRPVEFMTCkuZmluZGFsbChyZWdleF90YWcpWzBdCiAgICAgICAgICAgICMgbG9nZ2VyLmRlYnVnKHBhZ2UpCiAgICAgICAgZXhjZXB0OgogICAgICAgICAgICBwYWdlID0gIiIKCiAgICAgICAgcmVwZWF0X21vZGVfY2hlY2sgPSByZS5zZWFyY2goJzwuKj8+Lio/PC8uKj8+JywgbGlzdHJlcGVhdCwgcmUuRE9UQUxMKQogICAgICAgIGlmIHJlcGVhdF9tb2RlX2NoZWNrOgogICAgICAgICAgICBzZWxmLnJlcGVhdF9tb2RlID0gInJlcGVhdCIKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLnJlcGVhdF9tb2RlID0gInNpbmdsZSIKCiAgICAgICAgcmVnZXhfbW9kZV9jaGVjayA9IHJlLnNlYXJjaChyJyNcJHB5RnVuY3Rpb24nLCBleHByZXMsIHJlLkRPVEFMTCkKCiAgICAgICAgaWYgcmVnZXhfbW9kZV9jaGVjazoKICAgICAgICAgICAgc2VsZi5yZWdleF9tb2RlID0gInB5dGhvbiIKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLnJlZ2V4X21vZGUgPSAicmVnZXgiCgogICAgICAgIHJlZ2V4X3BhcmFtID0gcmUuY29tcGlsZShyJ1wkZG9yZWdleFxbLio/XF1cKCguKj8pXCknLCByZS5NVUxUSUxJTkUpLmZpbmRhbGwoaXRlbS51cmwpCiAgICAgICAgaWYgcmVnZXhfcGFyYW06CiAgICAgICAgICAgIHBhZ2UgPSByZWdleF9wYXJhbVswXQoKICAgICAgICBpZiBzZWxmLnJlcGVhdF9tb2RlID09ICJzaW5nbGUiIGFuZCBzZWxmLnJlZ2V4X21vZGUgPT0gInB5dGhvbiI6CiAgICAgICAgICAgIHJldHVybiBJdGVtUGFyc2VyLnBhcnNlX3B5X3JlZ2V4KGV4cHJlcywgaXRlbSwgcGFnZSkKCiAgICAgICAgaWYgc2VsZi5yZXBlYXRfbW9kZSA9PSAicmVwZWF0IiBhbmQgc2VsZi5yZWdleF9tb2RlID09ICJweXRob24iOgogICAgICAgICAgICBzZWxmLmJ1aWxkX2l0ZW1fcHkobGlzdHJlcGVhdCwgZXhwcmVzLCByZWdleF9uYW1lLCBwYWdlLCB4bWxfaXRlbSwgaXRlbSkKCiAgICAgICAgaWYgc2VsZi5yZXBlYXRfbW9kZSA9PSAicmVwZWF0IiBhbmQgc2VsZi5yZWdleF9tb2RlID09ICJyZWdleCI6CiAgICAgICAgICAgIHNlbGYuYnVpbGRfaXRlbV9yZShsaXN0cmVwZWF0LCBleHByZXMsIHJlZ2V4X25hbWUsIHBhZ2UsIHhtbF9pdGVtLCBpdGVtKQoKICAgICAgICByZXR1cm4gIiIKCiAgICBkZWYgYnVpbGRfaXRlbV9yZShzZWxmLCBzY2hlbWEsIGV4cHJlcywgcmVnZXhfbmFtZSwgcGFnZSwgcGFyZW50X3htbCwgaXRlbSk6CiAgICAgICAgbG9nZ2VyLmRlYnVnKCJfX19fX19fX19fX19fX19fIEJVSUxEIElURU0gUkUgX19fX19fX19fX19fX19fXyIpCiAgICAgICAgcGFnZSA9IHBhZ2UucmVwbGFjZSgiPCFbQ0RBVEFbIiwgIiIpLnJlcGxhY2UoIl1dPiIsICIiKQogICAgICAgIHBhZ2UgPSBzdXBwb3J0LmdldF96ZXJvbmV0X3BhZ2UocGFnZSkKICAgICAgICByID0gSHR0cENsaWVudCgpLmdldF9yZXF1ZXN0KHBhZ2UpCiAgICAgICAgZXhwcmVzID0gZXhwcmVzLnJlcGxhY2UoIjwhW0NEQVRBWyIsICIiKS5yZXBsYWNlKCJdXT4iLCAiIikKICAgICAgICByZXMgPSByZS5jb21waWxlKGV4cHJlcywgcmUuTVVMVElMSU5FKS5maW5kYWxsKHIudGV4dCkKCiAgICAgICAgc2VsZi5idWlsZF9pdGVtKHJlcywgcmVnZXhfbmFtZSwgc2NoZW1hLCBwYXJlbnRfeG1sLCBpdGVtKQoKICAgIGRlZiBidWlsZF9pdGVtX3B5KHNlbGYsIHNjaGVtYSwgZm4sIHJlZ2V4X25hbWUsIHBhZ2UsIHBhcmVudF94bWwsIGl0ZW0pOgogICAgICAgIGxvZ2dlci5kZWJ1ZygiX19fX19fX19fX19fX19fXyBCVUlMRCBJVEVNIFBZIF9fX19fX19fX19fX19fX18iKQogICAgICAgIHBhZ2UgPSBwYWdlLnJlcGxhY2UoIjwhW0NEQVRBWyIsICIiKS5yZXBsYWNlKCJdXT4iLCAiIikKICAgICAgICByZXMgPSBJdGVtUGFyc2VyLnBhcnNlX3B5X3JlZ2V4KGZuLCBpdGVtLCBwYWdlKQogICAgICAgIHNlbGYuYnVpbGRfaXRlbShyZXMsIHJlZ2V4X25hbWUsIHNjaGVtYSwgcGFyZW50X3htbCwgaXRlbSkKCiAgICBkZWYgYnVpbGRfaXRlbShzZWxmLCByZXMsIHJlZ2V4X25hbWUsIHNjaGVtYSwgcGFyZW50X3htbCwgaXRlbSk6CiAgICAgICAgbG9nZ2VyLmRlYnVnKCJfX19fX19fX19fX19fX19fIEJVSUxEIElURU0gX19fX19fX19fX19fX19fXyIpCgogICAgICAgIG91dHNjaGVtYSA9ICI8aXRlbT4iICsgc2NoZW1hICsgIjwvaXRlbT4iCiAgICAgICAgb3V0c2NoZW1hID0gb3V0c2NoZW1hLnJlcGxhY2UoIjwhW0NEQVRBWyIsICIiKS5yZXBsYWNlKCJdXT4iLCAiIikKCiAgICAgICAgc2VsZi5wYWdlX2xpc3QgPSBtUXVldWUuUXVldWUoKQoKICAgICAgICBleHRyYSA9IE5vbmUKICAgICAgICBpZiB0eXBlKHJlcykgaXMgZGljdDoKICAgICAgICAgICAgZXh0cmEgPSByZXNbImV4dHJhIl0KICAgICAgICAgICAgcmVzID0gcmVzWyJsaXN0Il0KCiAgICAgICAgc2VsZi5pdGVtX2J1aWxkZXIocmVzLCBvdXRzY2hlbWEsIGl0ZW0sIHJlZ2V4X25hbWUsIHBhcmVudF94bWwpCgogICAgICAgIGlmIGV4dHJhOgogICAgICAgICAgICBleHRyYV9zY2hlbWEgPSByZS5jb21waWxlKHInPGV4dHJhPiguKj8pPC9leHRyYT4nLCByZS5ET1RBTEwpLmZpbmRhbGwocGFyZW50X3htbClbMF0KICAgICAgICAgICAgb3V0c2NoZW1hID0gIjxpdGVtPiIgKyBleHRyYV9zY2hlbWEgKyAiPC9pdGVtPiIKICAgICAgICAgICAgb3V0c2NoZW1hID0gb3V0c2NoZW1hLnJlcGxhY2UoIjwhW0NEQVRBWyIsICIiKS5yZXBsYWNlKCJdXT4iLCAiIikKICAgICAgICAgICAgc2VsZi5pdGVtX2J1aWxkZXIoZXh0cmEsIG91dHNjaGVtYSwgaXRlbSwgcmVnZXhfbmFtZSwgcGFyZW50X3htbCkKCiAgICAgICAgc2VsZi5wYXJzZV9pdGVtX210KHNlbGYucGFnZV9saXN0LCBzaG93X3Byb2dyZXNzPVRydWUpCgogICAgZGVmIGl0ZW1fYnVpbGRlcihzZWxmLCByZXMsIG91dHNjaGVtYSwgaXRlbSwgcmVnZXhfbmFtZSwgcGFyZW50X3htbCk6CiAgICAgICAgbG9nZ2VyLmRlYnVnKCJfX19fX19fX19fX19fX19fIElURU0gQlVJTERFUiBfX19fX19fX19fX19fX19fIikKICAgICAgICBmb3IgciBpbiByZXM6CiAgICAgICAgICAgIG91dCA9IG91dHNjaGVtYQogICAgICAgICAgICByZWdleGVzID0gW10KCiAgICAgICAgICAgIGlmIGxlbihpdGVtLnJlZ2V4ZXMpID4gMDoKICAgICAgICAgICAgICAgIGZvciByZWdleHAgaW4gaXRlbS5yZWdleGVzOgogICAgICAgICAgICAgICAgICAgIGlmIHR5cGUocmVnZXhwKSA9PSBkaWN0OgogICAgICAgICAgICAgICAgICAgICAgICByZWdleHAgPSBUaGVncm9vdmVSZWdleGVzLmRpY3RfdG9fb2JqKHJlZ2V4cCkKICAgICAgICAgICAgICAgICAgICAjIGxvZ2dlci5kZWJ1ZyhyZWdleHAucGFyYW1zKQogICAgICAgICAgICAgICAgICAgIGlmIHJlZ2V4cC5uYW1lID09IHJlZ2V4X25hbWU6CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgZm9yIGosIHAgaW4gZW51bWVyYXRlKHJlZ2V4cC5wYXJhbXMpOgogICAgICAgICAgICAgICAgICAgICAgICBwcmludChwKTtvdXQgPSBvdXQucmVwbGFjZSgiWyIgKyByZWdleHAubmFtZSArICIucGFyYW0iICsgc3RyKChqICsgMSkpICsgIl0iLCBwLnN0cmlwKCkpCiAgICAgICAgICAgICAgICAgICAgcmVnZXhlcy5hcHBlbmQoVGhlZ3Jvb3ZlUmVnZXhlcyhuYW1lPXJlZ2V4cC5uYW1lLCBwYXJhbXM9cmVnZXhwLnBhcmFtcykpCgogICAgICAgICAgICBmb3IgaSwgcnBhcmFtIGluIGVudW1lcmF0ZShyKToKICAgICAgICAgICAgICAgICMgbG9nZ2VyLmRlYnVnKHJwYXJhbSkKICAgICAgICAgICAgICAgIHRvX3JlcGxhY2UgPSAiWyIgKyByZWdleF9uYW1lICsgIi5wYXJhbSIgKyBzdHIoKGkgKyAxKSkgKyAiXSIKICAgICAgICAgICAgICAgIGlmIHRvX3JlcGxhY2UgaW4gb3V0OgogICAgICAgICAgICAgICAgICAgIHJwID0gdScnLmpvaW4ocnBhcmFtKS5lbmNvZGUoInV0Zi04Iikuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIG91dCA9IG91dC5yZXBsYWNlKHRvX3JlcGxhY2UsIHJwLmRlY29kZSgndXRmLTgnLCAnaWdub3JlJykpCiAgICAgICAgICAgIHJlZ2V4ZXMuYXBwZW5kKFRoZWdyb292ZVJlZ2V4ZXMobmFtZT1yZWdleF9uYW1lLCBwYXJhbXM9cikpCgogICAgICAgICAgICAjIGxvZ2dlci5kZWJ1ZyhvdXQpCiAgICAgICAgICAgIHNlbGYucGFnZV9saXN0LnB1dCgob3V0LCBwYXJlbnRfeG1sLCByZWdleGVzKSkKCiAgICBkZWYgcGFyc2VfaXRlbV9tdChzZWxmLCBxdWV1ZSwgdXNlX2xvY2s9VHJ1ZSwgc2hvd19wcm9ncmVzcz1GYWxzZSk6CiAgICAgICAgZnJvbSByZXNvdXJjZXMubW9kdWxlcy5tdF93b3JrZXIgaW1wb3J0IE1UV29ya2VyCiAgICAgICAgTVRXb3JrZXIuc2V0X2pvYnMocXVldWUsIHNlbGYucGFyc2VfaXRlbSwgdXNlX2xvY2s9dXNlX2xvY2ssIHNob3dfcHJvZ3Jlc3M9c2hvd19wcm9ncmVzcykKCiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgaXNfcmVwZWF0X3JlZ2V4KG5hbWUsIHhtbCk6CiAgICAgICAgbG9nZ2VyLmRlYnVnKCJfX19fX19fX19fX19fX19fIElTIFJFUEVBVCBSRUdFWCBfX19fX19fX19fX19fX19fIikKICAgICAgICB0cnk6CiAgICAgICAgICAgIG5hbWUgPSByZS5jb21waWxlKHInXCRkb3JlZ2V4XFsoLio/KVxdJykuZmluZGFsbChuYW1lKVswXQogICAgICAgIGV4Y2VwdCBJbmRleEVycm9yOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAgICAgcmVnID0gcic8cmVnZXg+Lio/KDxuYW1lPicgKyBuYW1lICsgJzwvbmFtZT4uKj8pPC9yZWdleD4nCiAgICAgICAgbWF0Y2hlcyA9IHJlLmNvbXBpbGUocmVnLCByZS5TKS5maW5kYWxsKHhtbCkKCiAgICAgICAgaWYgbGVuKG1hdGNoZXMpID4gMDoKICAgICAgICAgICAgciA9IG1hdGNoZXNbMF0KICAgICAgICAgICAgbHJtcyA9IHJlLmNvbXBpbGUocic8bGlzdHJlcGVhdD4oLio/KTwvbGlzdHJlcGVhdD4nLCByZS5ET1RBTEwpLmZpbmRhbGwocikKICAgICAgICAgICAgaWYgbGVuKGxybXMpID4gMDoKICAgICAgICAgICAgICAgIGxybSA9IGxybXNbMF0KICAgICAgICAgICAgICAgIGxybSA9IGxybS5yZXBsYWNlKCI8IVtDREFUQVsiLCAiIikucmVwbGFjZSgiXV0+IiwgIiIpCiAgICAgICAgICAgICAgICBpZiBscm0gIT0gIiI6CiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIHJlcGxhY2VyKGZuLCBpdGVtKToKICAgICAgICBsb2dnZXIuZGVidWcoIl9fX19fX19fX19fX19SRVBMQUNFUl9fX19fX19fX19fX19fX19fIikKICAgICAgICByZXBsID0gcmUuY29tcGlsZShyJyhcWyguKj8pXC5wYXJhbShcZCspXF0pJykuZmluZGFsbChmbikKCiAgICAgICAgZnVuY3Rpb25zID0gZm4KCiAgICAgICAgZm9yIHJleCBpbiByZXBsOgogICAgICAgICAgICByciA9IHJleFswXQogICAgICAgICAgICBybmFtZSA9IHJleFsxXQogICAgICAgICAgICBycGFyID0gcmV4WzJdCiAgICAgICAgICAgIGZvciBwIGluIGl0ZW0ucmVnZXhlczoKICAgICAgICAgICAgICAgICMgbG9nZ2VyLmRlYnVnKHApCiAgICAgICAgICAgICAgICBpZiBwWyJuYW1lIl0gPT0gcm5hbWU6CiAgICAgICAgICAgICAgICAgICAgb3BhciA9ICIiCiAgICAgICAgICAgICAgICAgICAgaWYgcFsibmFtZSJdID09IHJuYW1lOgogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvcGFyID0gcFsicGFyYW1zIl1bKGludChycGFyKSAtIDEpXQogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgSW5kZXhFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9wYXIgPSAiIgogICAgICAgICAgICAgICAgICAgIGZ1bmN0aW9ucyA9IGZ1bmN0aW9ucy5yZXBsYWNlKHJyLCBvcGFyKQoKICAgICAgICAjIGxvZ2dlci5kZWJ1ZyhmdW5jdGlvbnMpCgogICAgICAgIHJldHVybiBmdW5jdGlvbnMKCiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgcGFyc2VfcHlfcmVnZXgoZm4sIGl0ZW0sIHBhZ2UpOgogICAgICAgIGxvZ2dlci5kZWJ1ZygiX19fX19fX19fX19fX19fXyBQQVJTRSBQWSBSRUdFWCBfX19fX19fX19fX19fX19fIikKICAgICAgICB0cnk6CiAgICAgICAgICAgICMgbG9nZ2VyLmRlYnVnKGZuKQogICAgICAgICAgICBmdW5jdGlvbnMgPSByZS5jb21waWxlKHInPCFcW0NEQVRBXFsjXCRweUZ1bmN0aW9uKC4qPyldXT4nLCByZS5ET1RBTEwpLmZpbmRhbGwoZm4pWzBdCiAgICAgICAgZXhjZXB0OgogICAgICAgICAgICByYWlzZQoKICAgICAgICBmdW5jdGlvbnMgPSBJdGVtUGFyc2VyLnJlcGxhY2VyKGZ1bmN0aW9ucywgaXRlbSkKICAgICAgICAjIGxvZ2dlci5kZWJ1ZyhmdW5jdGlvbnMpCiAgICAgICAgcGFnZSA9IHN1cHBvcnQuZ2V0X3plcm9uZXRfcGFnZShwYWdlKQoKICAgICAgICB4bWxfcHlfcmVzID0gIiIKICAgICAgICBpZiBmdW5jdGlvbnMgIT0gIiI6CiAgICAgICAgICAgIGZ1bmN0aW9ucyArPSAiXG54bWxfcHlfcmVzID0gZ2V0X3RoZWdyb292ZV94bWxfZm4oJyIgKyBwYWdlICsgIicpIgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBsb2MgPSB7fQogICAgICAgICAgICAgICAgZXhlYyhmdW5jdGlvbnMsIGdsb2JhbHMoKSwgbG9jKQogICAgICAgICAgICAgICAgIyBsb2dnZXIuZGVidWcobG9jKQogICAgICAgICAgICAgICAgeG1sX3B5X3JlcyA9IGxvY1sieG1sX3B5X3JlcyJdCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIGlmIGtvZGl1dGlscy5nZXRfc2V0dGluZ19hc19ib29sKCJkZWJ1ZyIpOgogICAgICAgICAgICAgICAgICAgIGltcG9ydCB0cmFjZWJhY2sKICAgICAgICAgICAgICAgICAgICB0cmFjZWJhY2sucHJpbnRfc3RhY2soKQogICAgICAgICAgICAgICAgICAgIGxvZ2dlci5kZWJ1ZyhzdHIoZSkpCiAgICAgICAgICAgICAgICByYWlzZSBlCgogICAgICAgICMgbG9nZ2VyLmRlYnVnKHR5cGUoeG1sX3B5X3JlcykpCiAgICAgICAgIyBsb2dnZXIuZGVidWcoeG1sX3B5X3JlcykKCiAgICAgICAgcmV0dXJuIHhtbF9weV9yZXM='


def _log(msg):
    try:
        from platformcode import logger
        logger.info('[TGEvents] %s' % msg)
    except Exception:
        pass


def _addon_path():
    """Compatibility hook: event loading never reads another installed add-on."""
    return None


def _key_lines():
    """TheGroove item_parser.py lines (AES key pool)."""
    base = _addon_path()
    if base:
        try:
            with open(os.path.join(base, 'resources', 'modules', 'item_parser.py'), encoding='utf-8') as f:
                lines = f.read().splitlines()
            if len(lines) >= 10:
                return lines
        except Exception as exc:
            _log('key pool from addon failed: %s' % str(exc))
    try:
        lines = base64.b64decode(_ITEM_PARSER_B64).decode('utf-8').splitlines()
        if len(lines) >= 10:
            return lines
    except Exception as exc:
        _log('embedded key pool failed: %s' % str(exc))
    raise RuntimeError('TheGroove item_parser key pool unavailable')


def _user_agents():
    base = _addon_path()
    if base:
        try:
            with open(os.path.join(base, 'resources', 'modules', 'UA.json'), encoding='utf-8') as f:
                uas = [e['ua'] for e in json.load(f) if isinstance(e, dict) and e.get('ua')]
            if uas:
                return uas
        except Exception as exc:
            _log('UA.json read failed: %s' % str(exc))
    return list(_UA_FALLBACK)


def _make_token(lines):
    ts = int(time.time())
    idx = ts % len(lines)
    prefix = str(len(str(idx))) + str(idx)
    n = 6 - len(prefix)
    r = random.randint(10 ** (n - 1), 10 ** n - 1)
    raw = '{}.{}{}'.format(ts, prefix, r)
    return idx, base64.urlsafe_b64encode(raw.encode('utf-8')).decode('ascii')


def _url_composer(page):
    """Replicates TheGrooveHTTPClient.url_composer exactly."""
    if '/thegroove/scripters/' in page and 'path=' in page:
        from urllib.parse import unquote
        scripter, spage = page.replace('/thegroove/scripters/', '').split('/', 1)
        page = 'php_script_loader?scripter=' + unquote(scripter) + '&' + unquote(spage)
    if '?' in page:
        # Original reassigns `page` to the head before appending (no raw query).
        page, params = page.split('?')
        if params != '':
            params = base64.urlsafe_b64encode(params.encode('utf-8')).decode('ascii')
            page += '&page_params=' + params
    return page


def _b64url_decode(data):
    if isinstance(data, bytes):
        data = data.decode('latin-1')
    # a2b_base64 ignores chars outside the alphabet; drop them so the padding
    # math below is exact (an internal newline would otherwise shift it).
    data = re.sub(r'[^A-Za-z0-9_\-]', '', data)
    pad = '=' * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + pad)
    except Exception:
        # addon's exact behavior: always append "=="
        return base64.urlsafe_b64decode(data + '==')


def _decrypt(lines, idx, payload):
    secret = lines[idx].strip()
    if len(secret) < 32:
        secret += ' ' * (32 - len(secret))
    else:
        secret = secret[:32]
    key = secret.encode('utf-8')
    iv = hashlib.sha256(key).hexdigest()[:16].encode('ascii')

    attempts = []  # (label, plaintext or None)
    try:
        from Crypto.Cipher import AES
        for label, seg in (('CFB8', None), ('CFB128', 128)):
            try:
                if seg is None:
                    cipher = AES.new(key, AES.MODE_CFB, iv)
                else:
                    cipher = AES.new(key, AES.MODE_CFB, iv, segment_size=seg)
                attempts.append((label, cipher.decrypt(_b64url_decode(payload))))
            except Exception as exc:
                _log('decrypt %s failed: %s' % (label, str(exc)))
                attempts.append((label, None))
    except ImportError:
        pass
    if not attempts:
        # Bundled pure-Python fallback (CFB8 = segment_size 1).
        try:
            from lib import pyaes as _pyaes
            for label, seg in (('pyaes-CFB8', 1), ('pyaes-CFB128', 16)):
                try:
                    # CFB is a *segment* mode in this pyaes build: its final()
                    # only accepts the default padding (it zero-pads and
                    # truncates internally). PADDING_NONE raises 'invalid
                    # padding option' on the flush call.
                    dec = _pyaes.Decrypter(_pyaes.AESModeOfOperationCFB(key, iv, segment_size=seg))
                    raw = _b64url_decode(payload)
                    attempts.append((label, dec.feed(raw) + dec.feed()))
                except Exception as exc:
                    _log('decrypt %s failed: %s' % (label, str(exc)))
                    attempts.append((label, None))
        except ImportError as exc:
            raise RuntimeError('no AES backend available: %s' % str(exc))

    for label, pt in attempts:
        if pt is not None:
            try:
                return pt.decode('utf-8')
            except UnicodeDecodeError:
                continue
    for label, pt in attempts:
        if pt is not None:
            return pt.decode('latin-1', errors='replace')
    raise RuntimeError('no decryption attempt produced output')


def _http_get(url, headers=None, timeout=20):
    """urllib GET with the same lax-SSL retry as sportchannels._urlopen_lax."""
    import ssl
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except Exception as exc:
        if 'CERTIFICATE_VERIFY_FAILED' not in str(exc):
            raise
        resp = urllib.request.urlopen(req, timeout=timeout,
                                      context=ssl._create_unverified_context())
    try:
        data = resp.read()
        hdrs = list(resp.getheaders())
    finally:
        resp.close()
    return data, hdrs


def _fetch_url(page):
    """Token + GET + header check + decrypt. Returns the decrypted page text."""
    lines = _key_lines()
    idx, token = _make_token(lines)
    if '/thegroove/scripters/' in page and 'path=' in page:
        composed = _url_composer(page)
    else:
        if page.startswith('/thegroove/'):
            page = page[len('/thegroove/'):]
        composed = _url_composer(page)
    url = SERVER + 'loader.php?page={}&token={}'.format(composed, token)
    headers = {
        'pragma': 'no-cache',
        'cache-control': 'no-cache',
        'dnt': '1',
        'upgrade-insecure-requests': '1',
        'accept': '*/*',
        'user-agent': random.choice(_user_agents()),
    }
    data, rh = _http_get(url, headers)
    got = None
    for k, v in rh:
        if k.lower() == 'thegroove':
            got = v
    if got != token:
        raise RuntimeError('Thegroove header mismatch (expected %s..., got %r)'
                           % (token[:12], str(got)[:40]))
    return _decrypt(lines, idx, data)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_EVENT_RE = re.compile(r'^(\d{2}:\d{2})\s*-\s*(.+?)\s*\(([^)]+)\)\s*$')

# Optional date prefix in a title, e.g. "26/10 18:45 - ..." or
# "Dom 26/10 18:45 - ...". The current page has no dates; this is for the day
# the server starts publishing multi-day schedules ("data se c'è").
_DATE_PREFIX_RE = re.compile(
    r'^(?:[A-Za-zÀ-ÿ]+\.?\s+)?(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+')

# "Oggi 18:45 - ..." / "Domani 18:45 - ..." style prefixes.
_DAY_WORD_RE = re.compile(r'^(oggi|domani)\b\.?\s+', re.I)

# Italian domestic competitions. League-based on purpose: "Premiership" in this
# feed is the Scottish league (Celtic vs Rangers), so team names are not a
# reliable signal for "italiani".
_ITALIAN_LEAGUE_RE = re.compile(
    r'(?i)\b(serie\s+[abc]|coppa\s+italia|supercoppa\s+italiana?)\b')


def _is_italian_league(league):
    return bool(_ITALIAN_LEAGUE_RE.search(league or ''))


def _date_key(date_s, today):
    """Sortable (y, m, d) for 'DD/MM[/YY]' strings; empty means today.

    A bare DD/MM that would land before today is assumed to be next year
    (e.g. 01/01 seen in December)."""
    if not date_s:
        return (today.year, today.month, today.day)
    try:
        parts = [int(p) for p in date_s.split('/')]
        if len(parts) == 2:
            d, mo = parts
            y = today.year + 1 if (mo, d) < (today.month, today.day) else today.year
        elif len(parts) == 3:
            d, mo, yy = parts
            y = 2000 + yy if yy < 100 else yy
        else:
            return (today.year, today.month, today.day)
    except ValueError:
        return (today.year, today.month, today.day)
    return (y, mo, d)


def _title_date(title, today):
    """If the title starts with a date prefix ("26/10", "Dom 26/10", "Oggi",
    "Domani"), return (date_s, rest_of_title); else ('', title)."""
    dm = _DATE_PREFIX_RE.match(title)
    if dm:
        return dm.group(1), title[dm.end():]
    wm = _DAY_WORD_RE.match(title)
    if wm:
        d = today + timedelta(days=1) if wm.group(1).lower() == 'domani' else today
        return d.strftime('%d/%m'), title[wm.end():]
    return '', title


def _sort_events(events):
    """Order: Italian matches first, then everything else; within each group by
    date (if any) and time. In-place."""
    today = date.today()

    def _key(e):
        return (0 if _is_italian_league(e.get('league')) else 1,
                _date_key(e.get('date') or '', today), e.get('time', ''), e.get('teams', ''))

    events.sort(key=_key)
    return events


def _strip_tags(s):
    s = re.sub(r'\[/?COLOR[^\]]*\]', '', s)
    s = re.sub(r'\[/?\w+\]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def _split_pipe(value):
    """Split "url|!Key=Val&Key2=Val2" into (url, headers). A suffix that does
    not start with '!' (e.g. "|force_isa=1") is a flag, not headers."""
    if '|' in value:
        url, _, rest = value.partition('|')
        if rest.startswith('!'):
            headers = {}
            for pair in rest[1:].split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    headers[k.strip()] = v.strip()
            return url.strip(), headers
        return url.strip(), {}
    return value.strip(), {}


def parse_events(text):
    """Extract match events and their playable sources from the decrypted page.

    An event is a <title> "HH:MM - Team A vs Team B (League)" followed by its
    link/sublink block; the block ends at the first </link> or next <title>.
    Titles may carry an optional date prefix ("26/10", "Dom 26/10", "Oggi",
    "Domani") which is stripped and used for ordering. AceStream links are
    ignored on purpose."""
    events = []
    seen_keys = set()
    today = date.today()
    for m in re.finditer(r'<title>(.*?)</title>', text, re.S):
        date_s, title = _title_date(_strip_tags(m.group(1)), today)
        mm = _EVENT_RE.match(title)
        if not mm:
            continue
        time_s, teams, league = (g.strip() for g in mm.groups())
        key = (date_s, time_s, teams)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        end_link = text.find('</link>', m.end())
        end_title = text.find('<title>', m.end())
        stops = [x for x in (end_link, end_title) if x != -1]
        seg = text[m.end():min(stops)] if stops else text[m.end():]

        sources = []
        seen_urls = set()
        for attrs, value in re.findall(r'<sublink([^>]*)>([^<]*)</sublink>', seg):
            value = value.strip()
            if not value or value.lower() == 'ignore':
                continue
            type_m = re.search(r'type="([^"]*)"', attrs)
            if type_m and type_m.group(1) == 'ace':
                continue                      # AceStream: ignored by design
            if re.fullmatch(r'[0-9a-fA-F]{40}', value):
                continue                      # bare ace hash, no type attr
            url, headers = _split_pipe(value)
            if not (url.startswith('http://') or url.startswith('https://')):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            kind = 'hls' if '.m3u8' in url else 'web'
            if kind == 'hls' and not headers.get('User-Agent'):
                headers['User-Agent'] = _UA_FALLBACK[0]
            sources.append({'kind': kind, 'url': url, 'headers': headers})

        thumb_m = re.search(r'<thumbnail>(.*?)</thumbnail>', seg, re.S)
        fanart_m = re.search(r'<fanart>(.*?)</fanart>', seg, re.S)
        full = u'%s %s (%s)' % (time_s, teams, league)
        if date_s:
            full = u'%s  %s' % (date_s, full)
        events.append({
            'time': time_s,
            'date': date_s,
            'teams': teams,
            'league': league,
            'fulltitle': full,
            'thumbnail': thumb_m.group(1).strip() if thumb_m else '',
            'fanart': fanart_m.group(1).strip() if fanart_m else '',
            'sources': sources,
        })

    _sort_events(events)
    return events


# ---------------------------------------------------------------------------
# Fetch + cache + row items
# ---------------------------------------------------------------------------

def fetch_events(page=DEFAULT_PAGE):
    """Fetch + decrypt + parse the events page. Returns a list of event dicts
    on success, None on any failure (caller keeps the previous row)."""
    try:
        text = _fetch_url(page)
        if '<title>' not in text:
            raise RuntimeError('decrypted payload has no <title> tags')
        events = parse_events(text)
        save_cache(events)
        return events
    except Exception as exc:
        _log('fetch failed: %s' % str(exc))
        return None


def _cache_path():
    from platformcode import config
    return os.path.join(config.get_data_path(), _CACHE_NAME)


def save_cache(events):
    try:
        path = _cache_path()
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'ts': time.time(), 'events': events}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        _log('save_cache failed: %s' % str(exc))


def load_cached(max_age=_CACHE_TTL):
    """Events from the last successful fetch (None if missing or stale)."""
    try:
        with open(_cache_path(), encoding='utf-8') as f:
            obj = json.load(f)
        if time.time() - float(obj.get('ts', 0)) <= max_age:
            # Re-sort so caches written by older code (no 'date' key, old
            # ordering) come out in the current Italian-first order too.
            return _sort_events(obj.get('events') or [])
    except Exception:
        pass
    return None


def cache_age():
    """Seconds since the last successful fetch (None if no valid cache).

    Used to keep every request — background cycle or on-demand click refresh —
    outside the server's per-page cooldown window."""
    try:
        with open(_cache_path(), encoding='utf-8') as f:
            obj = json.load(f)
        age = time.time() - float(obj.get('ts', 0))
        return age if age <= _CACHE_TTL else None
    except Exception:
        return None


def build_row_items(events, full_calendar=False):
    """Home-row items for the "Eventi Calcio" row (empty list → hidden row)."""
    from core.item import Item
    from platformcode import eventpresentation as presentation
    from platformcode import eventcalendar
    items = []
    for ev in eventcalendar.merge(events, home=not full_calendar):
        srcs = [s for s in (ev.get('sources') or []) if s.get('url')]
        it = Item(fulltitle=ev.get('fulltitle') or '', title=ev.get('teams') or '',
                  thumbnail='', fanart='', contentType='video', action='live_channel',
                  infoLabels={'_enr': 1, 'plot': ev['_status'] + '\n' + (ev.get('league') or '')})
        it.is_live_channel = True
        it._tg_event_sources = srcs
        home, away = presentation.teams(ev.get('teams') or '')
        it.event_home_badge = presentation.badge(home)
        it.event_away_badge = presentation.badge(away)
        it.event_home_initials = presentation.initials(home)
        it.event_away_initials = presentation.initials(away) if away else ''
        it.event_multi = '1' if presentation.is_multigol(ev.get('teams')) else ''
        if it.event_multi:
            it.event_home_initials = ''
            it.event_away_initials = ''
        it.event_status = presentation.event_status(ev)
        it.event_calendar_url = ev.get('calendar_url') or ''
        it.event_fixture = {key: ev.get(key) or '' for key in
                            ('teams', 'league', 'date', 'time', 'source_time', 'source_date', 'timezone')}
        it.event_league = ev.get('league') or ''
        items.append(it)
    return items


if __name__ == '__main__':
    # Standalone self-test: python -X utf8 tgevents.py
    evs = fetch_events()
    if evs is None:
        print('FETCH FAILED')
    else:
        print('%d events' % len(evs))
        for e in evs[:10]:
            print(u'%-6s %-45s [%s]  %d sources' % (e['time'], e['teams'][:45], e['league'], len(e['sources'])))
            for s in e['sources']:
                print('    %-4s %s%s' % (s['kind'], s['url'][:90], '  hdr=%d' % len(s['headers']) if s['headers'] else ''))
