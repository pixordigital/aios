# API Exemplos — Automações, WhatsApp, Uso

## Automações sem n8n
```bash
# criar workflow
curl -X POST /api/workflows -H "Authorization: Bearer $TOKEN" -d '{"name":"Lead→Slack"}'

# adicionar nó http_request
curl -X POST /api/workflows/$WF/nodes -d '{"label":"Slack","tool_name":"http_request","tool_args":{"url":"https://hooks.slack.com/...","method":"POST","body":{"text":"Novo lead {{json.json.name}}"}},"output_key":"slack"}'

# criar trigger webhook
curl -X POST /api/automations/workflows/$WF/triggers -d '{"type":"webhook","name":"Lead"}'
# → {"webhook_path":"wh_abc123"} → URL: /api/automations/webhook/wh_abc123

# usar template
curl -X POST /api/automations/templates/webhook_to_slack/create -d '{"name":"Meu Slack"}'
```

## WhatsApp Cloud API (100%)
```bash
# criar canal Meta
# Dashboard → Canais → WhatsApp → Meta → token + phone_id + template_name opcional

# enviar template via automação extra_data
{"whatsapp_type":"template","template_name":"hello_world","template_language":"pt_BR","template_params":["João"]}

# enviar mídia
{"whatsapp_type":"image","media_url":"https://example.com/img.jpg","caption":"Olá {{json.name}}"}
```

## Uso e Custo
```bash
curl /api/analytics/usage/monthly -H "Authorization: Bearer $TOKEN"
# → {total_tokens, total_cost, forecast_cost, pct_tokens, next_billing, remaining_days}

curl "/api/analytics/usage/daily?days=30"
curl /api/analytics/usage/agents
curl /api/analytics/usage/models
```

## Handover Humano
```bash
curl -X POST /api/conversations/$ID/handover -d '{"action":"take"}'  # pausa bot
curl -X POST /api/conversations/$ID/human-reply -d '{"content":"Olá, humano aqui"}'
```
