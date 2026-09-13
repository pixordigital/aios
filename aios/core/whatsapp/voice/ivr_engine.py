from dataclasses import dataclass, field

@dataclass
class IVRNode:
    id: str
    type: str  # greet|input|branch|transfer|hangup
    prompt: str = ""
    next_id: str | None = None

@dataclass
class IVRFlow:
    nodes: list[IVRNode] = field(default_factory=list)

    def add_greet(self, text: str) -> str:
        nid = f"n{len(self.nodes)+1}"
        self.nodes.append(IVRNode(id=nid, type="greet", prompt=text))
        return nid

def render_prompt(text: str, voice: str = "pf_dora(2)+bf_emma(1)") -> dict:
    """Renderiza via Kokoro (aios/core/voice)."""
    return {"text": text, "voice": voice, "engine": "kokoro"}

async def synthesize_ivr(flow: IVRFlow) -> list[dict]:
    from aios.core.voice import synthesize
    out=[]
    for n in flow.nodes:
        if n.type=="greet" and n.prompt:
            r = await synthesize(n.prompt, voice="pf_dora(2)+bf_emma(1)")
            out.append({"node": n.id, "ok": r.get("ok"), "bytes": r.get("bytes")})
    return out
