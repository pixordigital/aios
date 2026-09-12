# Evolution API Integration Tests

Two test suites for testing Evolution WhatsApp integration:

## 1. Direct Evolution API Test (`test_evolution_integration.py`)

Tests Evolution API directly without AIOS.

### Prerequisites
- Evolution API running (Docker/compose)
- Test WhatsApp number available

### Environment Variables
```bash
export EVOLUTION_SERVER_URL=http://localhost:8080
export EVOLUTION_API_KEY=evolution_secret_change_me
export TEST_WHATSAPP_NUMBER=5511999999999  # Your test number with country code
export EVOLUTION_CONNECT_TIMEOUT=120  # Optional: seconds to wait for connection
export PRINT_QR=1  # Optional: save QR code to /tmp
```

### Run
```bash
# Via pytest (skipped by default without env vars)
pytest tests/test_evolution_integration.py -v -s --run-evolution

# Or run directly (auto-loads env vars)
python tests/test_evolution_integration.py
```

### What it tests
1. Create Evolution instance
2. Get QR code
3. Wait for WhatsApp connection (manual QR scan required)
4. Send text message
5. Send media message
6. Cleanup instance

---

## 2. Via AIOS API Test (`test_evolution_via_aios.py`)

Tests Evolution integration through AIOS REST endpoints.

### Prerequisites
- AIOS running (default: http://localhost:8777)
- Evolution configured in AIOS (via .env or dashboard)
- Valid AIOS user credentials
- Evolution channel created in AIOS dashboard

### Environment Variables
```bash
export AIOS_URL=http://localhost:8777
export AIOS_TEST_EMAIL=admin@example.com
export AIOS_TEST_PASSWORD=yourpassword
export AIOS_TEST_CHANNEL_ID=channel-uuid-from-dashboard
export TEST_WHATSAPP_NUMBER=5511999999999
```

### Run
```bash
# Via pytest
pytest tests/test_evolution_via_aios.py -v -s

# Or run directly
python tests/test_evolution_via_aios.py
```

### What it tests
1. Login to AIOS
2. Create Evolution instance via AIOS
3. Get QR code via AIOS
4. List instances
5. Send message via AIOS channel endpoint

---

## Quick Setup with Docker Compose

```yaml
# docker-compose.evolution.yml
version: '3.8'
services:
  evolution:
    image: atendai/evolution-api:v2.3.7
    ports:
      - "8080:8080"
    environment:
      - AUTHENTICATION_API_KEY=evolution_secret_change_me
      - CONFIG_SESSION_PHONE_CLIENT=AIOS Test
      - CONFIG_SESSION_PHONE_NAME=AIOS Test
    volumes:
      - evolution_data:/data

  redis:
    image: redis:7-alpine

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=aios
      - POSTGRES_USER=aios
      - POSTGRES_PASSWORD=aios
    volumes:
      - pg_data:/var/lib/postgresql/data

volumes:
  evolution_data:
  pg_data:
```

```bash
docker-compose -f docker-compose.evolution.yml up -d
```

Then configure AIOS `.env`:
```env
AIOS_EVOLUTION_SERVER_URL=http://evolution:8080
AIOS_EVOLUTION_API_KEY=evolution_secret_change_me
```

---

## Test Number Tips

1. **Use a secondary WhatsApp number** (not your primary)
2. **WhatsApp Business API test numbers** work with Meta Cloud API provider
3. **Baileys (Web WhatsApp)** requires scanning QR with real phone
4. For CI/CD, consider using a dedicated test device with WhatsApp Web always logged in

---

## CI/CD Integration

```yaml
# .github/workflows/evolution-test.yml
name: Evolution Integration Test
on:
  workflow_dispatch:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM

jobs:
  test-evolution:
    runs-on: ubuntu-latest
    if: ${{ secrets.EVOLUTION_SERVER_URL != '' }}
    steps:
      - uses: actions/checkout@v4
      - name: Run Evolution Tests
        env:
          EVOLUTION_SERVER_URL: ${{ secrets.EVOLUTION_SERVER_URL }}
          EVOLUTION_API_KEY: ${{ secrets.EVOLUTION_API_KEY }}
          TEST_WHATSAPP_NUMBER: ${{ secrets.TEST_WHATSAPP_NUMBER }}
        run: |
          python tests/test_evolution_integration.py
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Instance not found" | Check instance name matches; Evolution may auto-delete inactive instances |
| QR code not generating | Ensure `qrcode: true` in create request; check Evolution logs |
| Connection timeout | Increase `EVOLUTION_CONNECT_TIMEOUT`; verify phone has internet |
| Message not delivered | Verify number format (no +, no @s.whatsapp.net); check Evolution logs |
| 401 Unauthorized | Check API key matches `AUTHENTICATION_API_KEY` in Evolution |

---

## Adding New Tests

1. Add test function to appropriate file
2. Use `@pytest.mark.asyncio` for async tests
3. Follow naming convention: `test_XX_description`
4. Use fixtures for shared setup (client, instance name)
5. Clean up in `finally` block or separate cleanup test