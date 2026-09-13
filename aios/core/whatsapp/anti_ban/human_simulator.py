import asyncio, random

async def human_delay(score: int = 0):
    """Delay log-normal simulando humano: score alto = mais rápido."""
    base = 1200 if score < 50 else 700
    jitter = random.randint(300, 2500)
    await asyncio.sleep((base + jitter)/1000)

def typing_duration(text: str) -> float:
    # ~40 wpm humano
    words = len((text or "").split())
    return max(0.8, min(4.5, words / 13 * 1.1 + random.uniform(0.3, 0.9)))
