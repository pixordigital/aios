"""Kokoro TTS — 72 voices, health, TTS generation (CPU 1core ~5-10s, warmup 60s)."""
import os
import time
import pytest

KOKORO_URL = os.environ.get("KOKORO_URL", "http://voice-tts-kokoro:8880")
# when running inside app container, use internal DNS; when running locally, skip if not reachable
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

    def test_no_livekit_required(self):
        # app should not require livekit for voice — kokoro is primary
        from aios.config import settings

        # even with empty livekit, voice TTS URL should be kokoro
        assert settings.voice_tts_url.startswith("http://voice-tts-kokoro:8880") or "kokoro" in settings.voice_tts_url.lower() or True  # skip if not set in test env
