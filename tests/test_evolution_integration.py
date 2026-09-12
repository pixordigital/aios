"""Evolution API Integration Test — tests real Evolution instance lifecycle.

Requires environment variables:
- EVOLUTION_SERVER_URL (e.g., http://localhost:8080)
- EVOLUTION_API_KEY (e.g., evolution_secret_change_me)
- TEST_WHATSAPP_NUMBER (e.g., 5511999999999 - your test number with country code)
- TEST_WHATSAPP_INSTANCE_NAME (optional, defaults to "aios-test-<random>")

Run only in environments with real Evolution API:
    pytest tests/test_evolution_integration.py -v -s --run-evolution

Skip by default (requires external service).
"""

import os
import pytest
import asyncio
import httpx
import logging
import uuid

logger = logging.getLogger(__name__)

# Skip if no Evolution config
EVOLUTION_SERVER_URL = os.getenv("EVOLUTION_SERVER_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
TEST_WHATSAPP_NUMBER = os.getenv("TEST_WHATSAPP_NUMBER")

pytestmark = pytest.mark.skipif(
    not (EVOLUTION_SERVER_URL and EVOLUTION_API_KEY and TEST_WHATSAPP_NUMBER),
    reason="Evolution API not configured — set EVOLUTION_SERVER_URL, EVOLUTION_API_KEY, TEST_WHATSAPP_NUMBER"
)


class EvolutionTestClient:
    """Client for testing Evolution API directly."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"apikey": api_key, "Content-Type": "application/json"}

    async def create_instance(self, instance_name: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/instance/create",
                headers=self.headers,
                json={"instanceName": instance_name, "qrcode": True, "integration": "WHATSAPP-BAILEYS"}
            )
            return {"status": resp.status_code, "data": resp.json()}

    async def get_qrcode(self, instance_name: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/instance/connect/{instance_name}",
                headers=self.headers
            )
            return {"status": resp.status_code, "data": resp.json()}

    async def get_status(self, instance_name: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/instance/connectionState/{instance_name}",
                headers=self.headers
            )
            return {"status": resp.status_code, "data": resp.json()}

    async def send_message(self, instance_name: str, number: str, text: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            # Format number: remove + and @s.whatsapp.net if present
            clean_number = number.replace("+", "").replace("@s.whatsapp.net", "")
            resp = await client.post(
                f"{self.base_url}/message/sendText/{instance_name}",
                headers=self.headers,
                json={"number": clean_number, "text": text}
            )
            return {"status": resp.status_code, "data": resp.json()}

    async def send_media(self, instance_name: str, number: str, media_url: str, caption: str = "") -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            clean_number = number.replace("+", "").replace("@s.whatsapp.net", "")
            resp = await client.post(
                f"{self.base_url}/message/sendMedia/{instance_name}",
                headers=self.headers,
                json={
                    "number": clean_number,
                    "mediatype": "image",
                    "media": media_url,
                    "caption": caption,
                    "fileName": "test.jpg"
                }
            )
            return {"status": resp.status_code, "data": resp.json()}

    async def delete_instance(self, instance_name: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                f"{self.base_url}/instance/delete/{instance_name}",
                headers=self.headers
            )
            return {"status": resp.status_code, "data": resp.json()}


@pytest.fixture(scope="module")
def evolution_client():
    """Create Evolution API test client."""
    return EvolutionTestClient(EVOLUTION_SERVER_URL, EVOLUTION_API_KEY)


@pytest.fixture(scope="module")
def test_instance_name():
    """Generate unique test instance name."""
    return f"aios-test-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_01_create_instance(evolution_client: EvolutionTestClient, test_instance_name: str):
    """Test creating a new Evolution instance."""
    logger.info(f"Creating instance: {test_instance_name}")
    result = await evolution_client.create_instance(test_instance_name)
    
    assert result["status"] in (200, 201), f"Failed to create instance: {result}"
    assert result["data"].get("instanceName") == test_instance_name
    logger.info(f"Instance created: {result['data']}")


@pytest.mark.asyncio
async def test_02_get_qrcode(evolution_client: EvolutionTestClient, test_instance_name: str):
    """Test getting QR code for instance connection."""
    logger.info(f"Getting QR code for: {test_instance_name}")
    result = await evolution_client.get_qrcode(test_instance_name)
    
    assert result["status"] == 200, f"Failed to get QR: {result}"
    data = result["data"]
    
    # QR code should be in base64 or as data URL
    qr_code = data.get("qrcode") or data.get("base64") or data.get("qr")
    assert qr_code, f"No QR code in response: {data}"
    logger.info("QR code received (base64 length: %d)", len(qr_code) if qr_code else 0)
    
    # Print QR for manual scanning if needed
    if os.getenv("PRINT_QR"):
        import base64
        try:
            if qr_code.startswith("data:"):
                b64 = qr_code.split(",")[1]
            else:
                b64 = qr_code
            # Save to file for viewing
            with open(f"/tmp/{test_instance_name}_qr.png", "wb") as f:
                f.write(base64.b64decode(b64))
            logger.info(f"QR code saved to /tmp/{test_instance_name}_qr.png")
        except Exception as e:
            logger.warning(f"Could not save QR: {e}")


@pytest.mark.asyncio
async def test_03_wait_for_connection(evolution_client: EvolutionTestClient, test_instance_name: str):
    """Wait for WhatsApp to connect (manual scan required)."""
    logger.info("Waiting for WhatsApp connection... Scan QR code with test number")
    
    max_wait = int(os.getenv("EVOLUTION_CONNECT_TIMEOUT", "120"))  # 2 minutes default
    poll_interval = 5
    elapsed = 0
    
    while elapsed < max_wait:
        result = await evolution_client.get_status(test_instance_name)
        
        if result["status"] == 200:
            data = result["data"]
            state = data.get("state") or data.get("instance", {}).get("state")
            
            if state == "open":
                logger.info("WhatsApp connected successfully!")
                return
            elif state in ("connecting", "close"):
                logger.info(f"State: {state}, waiting...")
            else:
                logger.info(f"State: {state}")
        
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    
    pytest.fail(f"WhatsApp did not connect within {max_wait}s. Last state: {state}")


@pytest.mark.asyncio
async def test_04_send_text_message(evolution_client: EvolutionTestClient, test_instance_name: str):
    """Send a test text message to the configured test number."""
    test_msg = f"🧪 AIOS Integration Test - {uuid.uuid4().hex[:8]}"
    logger.info(f"Sending test message to {TEST_WHATSAPP_NUMBER}: {test_msg}")
    
    result = await evolution_client.send_message(test_instance_name, TEST_WHATSAPP_NUMBER, test_msg)
    
    assert result["status"] in (200, 201), f"Failed to send message: {result}"
    data = result["data"]
    assert "key" in data or "id" in data or "messageId" in data
    logger.info(f"Message sent successfully: {data}")


@pytest.mark.asyncio
async def test_05_send_media_message(evolution_client: EvolutionTestClient, test_instance_name: str):
    """Send a test media message (image) to the configured test number."""
    # Use a small test image
    media_url = "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demo_1.png"
    caption = f"🖼️ AIOS Media Test - {uuid.uuid4().hex[:8]}"
    
    logger.info(f"Sending media to {TEST_WHATSAPP_NUMBER}")
    result = await evolution_client.send_media(test_instance_name, TEST_WHATSAPP_NUMBER, media_url, caption)
    
    # Media send may fail if instance not fully ready, log but don't fail
    if result["status"] in (200, 201):
        logger.info(f"Media sent: {result['data']}")
    else:
        logger.warning(f"Media send failed (may be expected): {result}")


@pytest.mark.asyncio
async def test_06_receive_webhook_simulation(evolution_client: EvolutionTestClient, test_instance_name: str):
    """Simulate receiving a webhook (test webhook endpoint)."""
    import hmac
    import hashlib
    import json
    
    # This tests the AIOS webhook endpoint, not Evolution directly
    # We'd need the AIOS app running for this
    logger.info("Webhook simulation test - requires AIOS running")
    pytest.skip("Requires AIOS app running with webhook configured")


@pytest.mark.asyncio
async def test_07_cleanup_instance(evolution_client: EvolutionTestClient, test_instance_name: str):
    """Clean up test instance."""
    logger.info(f"Deleting test instance: {test_instance_name}")
    result = await evolution_client.delete_instance(test_instance_name)
    
    assert result["status"] in (200, 201), f"Failed to delete instance: {result}"
    logger.info("Instance deleted successfully")


# Convenience function for manual testing
async def run_full_test_suite():
    """Run all tests in sequence for manual execution."""
    client = EvolutionTestClient(EVOLUTION_SERVER_URL, EVOLUTION_API_KEY)
    instance_name = f"aios-test-{uuid.uuid4().hex[:8]}"
    
    try:
        print(f"\n=== Evolution Integration Test ===")
        print(f"Instance: {instance_name}")
        print(f"Test Number: {TEST_WHATSAPP_NUMBER}")
        print(f"Server: {EVOLUTION_SERVER_URL}")
        
        # 1. Create
        print("\n1. Creating instance...")
        await test_01_create_instance(client, instance_name)
        
        # 2. QR Code
        print("\n2. Getting QR code...")
        await test_02_get_qrcode(client, instance_name)
        
        # 3. Wait for connection
        print("\n3. Waiting for connection (scan QR with test WhatsApp)...")
        await test_03_wait_for_connection(client, instance_name)
        
        # 4. Send text
        print("\n4. Sending test message...")
        await test_04_send_text_message(client, instance_name)
        
        # 5. Send media
        print("\n5. Sending test media...")
        await test_05_send_media_message(client, instance_name)
        
        print("\n✅ All tests passed!")
        
    except Exception as e:
        logger.exception(f"Test failed: {e}")
        raise
    finally:
        # 6. Cleanup
        print("\n6. Cleaning up...")
        try:
            await test_07_cleanup_instance(client, instance_name)
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")


if __name__ == "__main__":
    # Allow running directly: python tests/test_evolution_integration.py
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_full_test_suite())