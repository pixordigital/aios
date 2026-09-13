from prometheus_client import Counter, Gauge
msg_total = Counter("whatsapp_messages_total","total",["instance","direction","status"])
ban_risk = Gauge("whatsapp_ban_risk_score","risk",["instance"])
call_mos = Gauge("whatsapp_call_mos","MOS",["instance"])
