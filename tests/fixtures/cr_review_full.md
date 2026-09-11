<!-- This is what CodeRabbit posts as a review body on a PR. -->
**Actionable comments posted: 4**

<details>
<summary>🔭 Outside diff range comments (1)</summary>

`src/api/handlers.py`

`142-158`: **⚠️ Potential issue**

The exception handler catches `Exception` too broadly and swallows stack traces. This masks bugs from observability.

Replace with narrower exception types (`ValueError`, `KeyError`) and re-raise unexpected exceptions after logging.

```python
except (ValueError, KeyError) as exc:
    log.warning("bad input", exc_info=exc)
    return HTTPResponse(400, str(exc))
```

</details>

<details>
<summary>📝 Comments (3)</summary>

`src/api/handlers.py`

`24-30`: **🛠️ Refactor suggestion**

Repeated string concatenation for building the URL is fragile. Use `urllib.parse.urljoin` or `httpx.URL`.

`src/models/user.py`

`88`: **🧹 Nitpick (assertive)**

Variable name `usr` is inconsistent with `user` used elsewhere in the same class. Rename for consistency.

`tests/test_api.py`

`45-52`: **✅ Verification agent**

Verify that this test actually asserts against the mocked response — the `assert response.status_code == 200` line was moved but the test still passes trivially.

</details>
