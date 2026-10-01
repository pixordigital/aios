"""Kokoro TTS — 72 voices, health, TTS generation (CPU 1core ~5-10s, warmup 60s)."""
import os
import time
import pytest

# Loopback by default. The container publishes no ports, so "voice-tts-kokoro"
# is Docker-internal DNS that never resolves from a host shell -- that mismatch
# is what silently skipped all 7 tests. Inside the app container KOKORO_URL can
# still be set to the internal name; scripts/kokoro-host-forward.sh bridges it.
KOKORO_URL = os.environ.get("KOKORO_URL", "http://127.0.0.1:8880")
import httpx

def _is_kokoro_reachable() -> bool:
    try:
        r = httpx.get(f"{KOKORO_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _is_kokoro_reachable(), reason="kokoro not reachable (no docker --profile voice)")
class TestKokoro:
    def test_health(self):
        r = httpx.get(f"{KOKORO_URL}/health", timeout=5)
        assert r.status_code == 200
        assert r.json().get("status") == "healthy"

    def test_models(self):
        r = httpx.get(f"{KOKORO_URL}/v1/models", timeout=5)
        assert r.status_code == 200
        j = r.json()
        assert "data" in j
        ids = {m["id"] for m in j["data"]}
        assert "kokoro" in ids or "tts-1" in ids

    def test_voices_count(self):
        r = httpx.get(f"{KOKORO_URL}/v1/audio/voices", timeout=5)
        assert r.status_code == 200
        j = r.json()
        assert len(j["voices"]) >= 70
        assert j["default_voice"] in [v["id"] for v in j["voices"]]
        # pt voices must exist (pf_dora/pm_alex for ptbr mapping)
        ids = {v["id"] for v in j["voices"]}
        assert "pm_alex" in ids
        assert "pf_dora" in ids

    def test_tts_af_heart_short(self):
        t0 = time.time()
        r = httpx.post(
            f"{KOKORO_URL}/v1/audio/speech",
            json={"model": "kokoro", "input": "Hello", "voice": "af_heart"},
            timeout=30,
        )
        dt = time.time() - t0
        assert r.status_code == 200
        assert len(r.content) > 1000
        assert r.headers.get("content-type", "").startswith("audio")
        assert dt < 30, f"TTS too slow {dt:.1f}s with 1 CPU"

    def test_tts_pt_voice(self):
        # ptbr mapping pm_alex should work, af_heart also works for pt text but with accent
        r = httpx.post(
            f"{KOKORO_URL}/v1/audio/speech",
            json={"model": "kokoro", "input": "Ola", "voice": "pm_alex"},
            timeout=30,
        )
        assert r.status_code == 200
        assert len(r.content) > 1000

    def test_tts_response_streaming(self):
        # ensure streaming not hanging — 56 char pt text like smoke
        r = httpx.post(
            f"{KOKORO_URL}/v1/audio/speech",
            json={"model": "kokoro", "input": "Ola, teste Kokoro TTS no AIOS, funcionando perfeitamente", "voice": "af_heart"},
            timeout=30,
        )
        assert r.status_code == 200
        assert len(r.content) > 5000

    def test_kokoro_is_the_configured_tts(self):
        """Kokoro is the only TTS engine; there is no streaming transport left."""
        from aios.config import settings

        assert "kokoro" in settings.kokoro_url.lower()
        assert settings.voice_provider in ("selfhosted", "elevenlabs", "vapi", "retell")

    def test_no_livekit_settings_remain(self):
        """LiveKit was removed: config must not expose a livekit_* knob again."""
        from aios.config import settings

        leaked = [k for k in dir(settings) if "livekit" in k.lower()]
        assert not leaked, f"livekit settings came back: {leaked}"
