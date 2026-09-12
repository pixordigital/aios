"""Evolution API test via AIOS Dashboard API.

Tests the Evolution integration through AIOS REST endpoints:
- Create instance via /api/channels/evolution/create-instance
- Get QR code via /api/channels/evolution/qrcode
- List instances
- Send test message

Requires:
- AIOS running (localhost:8777 by default)
- EVOLUTION_SERVER_URL, EVOLUTION_API_KEY configured in AIOS
- Valid auth token (login first)

Usage:
    pytest tests/test_evolution_via_aios.py -v -s
"""

import os
import pytest
import asyncio
import httpx
import uuid

logger = logging.getLogger(__name__)

AIOS_URL = os.getenv("AIOS_URL", "http://localhost:8777")
AIOS_EMAIL = os.getenv("AIOS_TEST_EMAIL")
AIOS_PASSWORD = os.getenv("AIOS_TEST_PASSWORD")
TEST_WHATSAPP_NUMBER = os.getenv("TEST_WHATSAPP_NUMBER")

pytestmark = pytest.mark.skipif(
    not (AIOS_EMAIL and AIOS_PASSWORD and TEST_WHATSAPP_NUMBER),
    reason="AIOS credentials not configured — set AIOS_TEST_EMAIL, AIOS_TEST_PASSWORD, TEST_WHATSAPP_NUMBER"
)


class AIOSTestClient:
    """Client for testing AIOS API endpoints."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token = None
        self.headers = {"Content-Type": "application/json"}

    async def login(self, email: str, password: str) -> str:
        """Login and get JWT token."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/api/auth/login",
                json={"email": email, "password": password}
            )
            if resp.status_code != 200:
                raise Exception(f"Login failed: {resp.status_code} {resp.text}")
            data = resp.json()
            self.token = data["access_token"]
            self.headers["Authorization"] = f"Bearer {self.token}"
            return self.token

    async def create_evolution_instance(self, instance_name: str) -> dict:
        """Create Evolution instance via AIOS."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/api/channels/evolution/create-instance",
                headers=self.headers,
                json={"instance_name": instance_name, "provider": "baileys"}
            )
            return {"status": resp.status_code, "data": resp.json()}

    async def list_evolution_instances(self, channel_id: str) -> dict:
        """List Evolution instances for a channel."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/api/channels/evolution/list-instances",
                headers=self.headers,
                params={"channel_id": channel_id}
            )
            return {"status": resp.status_code, "data": resp.json()}

    async def get_qrcode(self, channel_id: str, instance_name: str) -> dict:
        """Get QR code for Evolution instance."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/api/channels/evolution/qrcode",
                headers=self.headers,
                params={"channel_id": channel_id, "instance_name": instance_name}
            )
            return {"status": resp.status_code, "data": resp.json()}

    async def send_whatsapp_message(self, channel_id: str, number: str, text: str) -> dict:
        """Send WhatsApp message via Evolution channel."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/api/channels/{channel_id}/send",
                headers=self.headers,
                json={"to": number, "text": text}
            )
            return {"status": resp.status_code, "data": resp.json()}


@pytest.fixture(scope="module")
async def aios_client():
    """Create and login AIOS test client."""
    client = AIOSTestClient(AIOS_URL)
    await client.login(AIOS_EMAIL, AIOS_PASSWORD)
    return client


@pytest.fixture(scope="module")
async def test_channel_id(aios_client: AIOSTestClient):
    """Create or find an Evolution channel for testing."""
    # For this test, we assume a channel already exists
    # In real scenario, you'd create one via /api/channels
    channel_id = os.getenv("AIOS_TEST_CHANNEL_ID")
    if not channel_id:
        pytest.skip("AIOS_TEST_CHANNEL_ID not set")
    return channel_id


@pytest.fixture(scope="module")
def test_instance_name():
    """Generate unique test instance name."""
    return f"aios-test-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_create_instance_via_aios(aios_client: AIOSTestClient, test_channel_id: str, test_instance_name: str):
    """Create Evolution instance through AIOS API."""
    logger.info(f"Creating instance via AIOS: {test_instance_name}")
    result = await aios_client.create_evolution_instance(test_instance_name)
    
    assert result["status"] in (200, 201), f"Failed: {result}"
    data = result["data"]
    assert data.get("ok") is True
    logger.info(f"Instance created: {data}")


@pytest.mark.asyncio
async def test_get_qrcode_via_aios(aios_client: AIOSTestClient, test_channel_id: str, test_instance_name: str):
    """Get QR code through AIOS."""
    result = await aios_client.get_qrcode(test_channel_id, test_instance_name)
    
    assert result["status"] == 200
    data = result["data"]
    # QR may be in connect.data.qrcode or direct
    qr = data.get("qrcode") or data.get("connect", {}).get("data", {}).get("qrcode") or data.get("base64")
    assert qr, f"No QR code: {data}"
    logger.info("QR code received via AIOS")


@pytest.mark.asyncio
async def test_list_instances(aios_client: AIOSTestClient, test_channel_id: str):
    """List Evolution instances."""
    result = await aios_client.list_evolution_instances(test_channel_id)
    
    assert result["status"] == 200
    data = result["data"]
    assert "instances" in data or isinstance(data, list)
    logger.info(f"Instances: {data}")


@pytest.mark.asyncio
async def test_send_message_via_aios(aios_client: AIOSTestClient, test_channel_id: str):
    """Send test message through AIOS."""
    test_msg = f"🧪 AIOS API Test - {uuid.uuid4().hex[:8]}"
    logger.info(f"Sending message to {TEST_WHATSAPP_NUMBER}")
    
    result = await aios_client.send_whatsapp_message(test_channel_id, TEST_WHATSAPP_NUMBER, test_msg)
    
    assert result["status"] in (200, 201), f"Failed: {result}"
    logger.info(f"Message sent: {result['data']}")


# Manual run
async def run_manual_test():
    """Run manually for quick testing."""
    logging.basicConfig(level=logging.INFO)
    
    client = AIOSTestClient(AIOS_URL)
    await client.login(AIOS_EMAIL, AIOS_PASSWORD)
    
    instance_name = f"aios-test-{uuid.uuid4().hex[:8]}"
    channel_id = os.getenv("AIOS_TEST_CHANNEL_ID")
    
    if not channel_id:
        print("ERROR: Set AIOS_TEST_CHANNEL_ID")
        return
    
    print(f"\n=== AIOS Evolution Test ===")
    print(f"URL: {AIOS_URL}")
    print(f"Instance: {instance_name}")
    print(f"Channel: {channel_id}")
    print(f"Test Number: {TEST_WHATSAPP_NUMBER}")
    
    # Create instance
    print("\n1. Creating instance...")
    result = await client.create_evolution_instance(instance_name)
    print(f"   Result: {result}")
    
    if result["status"] not in (200, 201):
        print("Failed to create instance")
        return
    
    # Get QR
    print("\n2. Getting QR code...")
    result = await client.get_qrcode(channel_id, instance_name)
    print(f"   QR received: {'Yes' if result['status'] == 200 else 'No'}")
    
    print("\n3. Scan QR with test WhatsApp, then press Enter...")
    input()
    
    # Send message
    print("\n4. Sending test message...")
    result = await client.send_whatsapp_message(channel_id, TEST_WHATSAPP_NUMBER, "Test from AIOS API!")
    print(f"   Result: {result}")


if __name__ == "__main__":
    asyncio.run(run_manual_test())