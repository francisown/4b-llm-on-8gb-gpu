"""Regression check for the isolated-surrogate multi-turn chat failure."""

from openai._utils._json import openapi_dumps

from chat import normalize_unicode


bad_text = "介绍苏州\udce4"
try:
    openapi_dumps({"content": bad_text})
except UnicodeEncodeError as exc:
    print("RED reproduced:", type(exc).__name__, repr(bad_text))
else:
    raise AssertionError("The fixture should reproduce the original failure")

safe_text = normalize_unicode(bad_text)
encoded = openapi_dumps({"content": safe_text})
assert not any(0xD800 <= ord(char) <= 0xDFFF for char in safe_text)
assert encoded
print("GREEN normalized:", repr(safe_text))
