# Auth Tests

> 16 nodes · cohesion 0.17

## Key Concepts

- **TestAuth** (8 connections) — `tests/test_auth.py`
- **AsyncClient** (7 connections)
- **test_auth.py** (3 connections) — `tests/test_auth.py`
- **.test_login_invalid_password()** (3 connections) — `tests/test_auth.py`
- **.test_password_validation()** (3 connections) — `tests/test_auth.py`
- **.test_refresh_token()** (3 connections) — `tests/test_auth.py`
- **.test_refresh_token_invalid()** (3 connections) — `tests/test_auth.py`
- **.test_register()** (3 connections) — `tests/test_auth.py`
- **.test_register_duplicate_email()** (3 connections) — `tests/test_auth.py`
- **.test_login()** (2 connections) — `tests/test_auth.py`
- **Test user registration.** (1 connections) — `tests/test_auth.py`
- **Test invalid refresh token fails.** (1 connections) — `tests/test_auth.py`
- **Test password validation on register.** (1 connections) — `tests/test_auth.py`
- **Test registering with existing email fails.** (1 connections) — `tests/test_auth.py`
- **Test login with wrong password fails.** (1 connections) — `tests/test_auth.py`
- **Test refresh token endpoint.** (1 connections) — `tests/test_auth.py`

## Relationships

- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)

## Source Files

- `tests/test_auth.py`

## Audit Trail

- EXTRACTED: 23 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*