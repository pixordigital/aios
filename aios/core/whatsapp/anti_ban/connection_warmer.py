"""Warmup conservador por instância: 5→10→20→40→80→150→300 msgs/dia por semana."""

CURVES = {
    "conservative": [5,10,20,40,80,150,300],
    "balanced": [10,25,50,100,200,400,800],
    "aggressive": [20,50,100,200,400,800,1500],
}

def daily_limit(warmup_stage: int, curve: str = "conservative") -> int:
    c = CURVES.get(curve, CURVES["conservative"])
    return c[min(warmup_stage, len(c)-1)]

def is_allowed(sent_today: int, warmup_stage: int, curve: str = "conservative") -> bool:
    return sent_today < daily_limit(warmup_stage, curve)
