def mos_from_metrics(jitter_ms: float, loss_pct: float, rtt_ms: float) -> float:
    # E-model simplificado 1.0-4.5
    score = 4.5 - (jitter_ms/80)*0.5 - (loss_pct/5)*0.7 - (rtt_ms/400)*0.4
    return max(1.0, min(4.5, round(score,2)))

def fallback_chain(mos: float) -> str:
    if mos >= 3.5: return "webrtc"
    if mos >= 2.5: return "audio_only"
    return "voicemail"
