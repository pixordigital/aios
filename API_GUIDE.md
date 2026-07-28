# AIOS API Guide

Base URL: `https://your-domain.com/api`

## Authentication

All endpoints (except `/api/auth/*`) require `Authorization: Bearer <token>` header.

**Get a token:**
```bash
# Register
curl -X POST https://your-domain.com/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@company.com","password":"secret123","org_name":"My Company"}'

# Login
curl -X POST https://your-domain.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@company.com","password":"secret123"}'
```

Response: `{"access_token":"eyJ...","refresh_token":"eyJ...","user_id":"...","org_id":"..."}`

**Refresh token:**
```bash
curl -X POST https://your-domain.com/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"eyJ..."}'
```

## OAuth Login

```bash
# Google
curl https://your-domain.com/api/auth/google/login
# Returns {"authorization_url":"https://accounts.google.com/o/oauth2/v2/auth?..."}

# GitHub
curl https://your-domain.com/api/auth/github/login
# Returns {"authorization_url":"https://github.com/login/oauth/authorize?..."}
```

## Endpoints

### Agents

```bash
# Create
curl -X POST https://your-domain.com/api/agents \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"My Agent","agent_type":"sdr","llm_config":{"model":"openai/gpt-4o"}}'

# List (paginated)
curl "https://your-domain.com/api/agents?limit=20&offset=0" \
  -H "Authorization: Bearer TOKEN"

# Get
curl https://your-domain.com/api/agents/AGENT_ID \
  -H "Authorization: Bearer TOKEN"

# Update
curl -X PUT https://your-domain.com/api/agents/AGENT_ID \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Name","governance_config":{"autonomy":"autonomous","denied_tools":["send_email"]}}'

# Delete
curl -X DELETE https://your-domain.com/api/agents/AGENT_ID \
  -H "Authorization: Bearer TOKEN"

# Deploy (activate)
curl -X POST https://your-domain.com/api/agents/AGENT_ID/deploy \
  -H "Authorization: Bearer TOKEN"

# Stop
curl -X POST https://your-domain.com/api/agents/AGENT_ID/stop \
  -H "Authorization: Bearer TOKEN"
```

### Agent Governance Config

```json
{
  "autonomy": "draft",        // "autonomous" | "draft" | "ask"
  "max_tokens_per_run": 500000,
  "allowed_tools": "__all__", // "__all__" or ["calculator","web_search"]
  "denied_tools": ["send_email"],
  "max_iterations": 10
}
```

### Teams

```bash
# Create
curl -X POST https://your-domain.com/api/teams \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Sales Team","routing_strategy":"supervisor"}'

# List
curl "https://your-domain.com/api/teams?limit=20&offset=0" \
  -H "Authorization: Bearer TOKEN"

# Assign agents
curl -X POST https://your-domain.com/api/teams/TEAM_ID/assign \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_ids":["agent_1","agent_2"]}'
```

### Conversations

```bash
# Create
curl -X POST https://your-domain.com/api/conversations \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"AGENT_ID","channel":"web"}'

# Send message (non-streaming)
curl -X POST https://your-domain.com/api/conversations/CONV_ID/messages \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Hello!"}'

# Send message (SSE streaming)
curl -X POST https://your-domain.com/api/conversations/CONV_ID/messages/stream \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Hello!"}'

# Get messages
curl "https://your-domain.com/api/conversations/CONV_ID/messages?limit=50" \
  -H "Authorization: Bearer TOKEN"
```

### Channels

```bash
# Create
curl -X POST https://your-domain.com/api/channels \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel_type":"whatsapp","label":"Support Line","config":{"phone_id":"...","access_token":"..."}}'

# List
curl "https://your-domain.com/api/channels?limit=20&offset=0" \
  -H "Authorization: Bearer TOKEN"

# Toggle active
curl -X PATCH https://your-domain.com/api/channels/CHANNEL_ID/toggle \
  -H "Authorization: Bearer TOKEN"
```

### Tools

```bash
# List
curl "https://your-domain.com/api/tools?limit=20&offset=0" \
  -H "Authorization: Bearer TOKEN"

# Create
curl -X POST https://your-domain.com/api/tools \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my_tool","description":"Does something","input_schema":{},"output_schema":{}}'
```

### Billing

```bash
# Get plans
curl https://your-domain.com/api/billing/plans

# Get usage
curl https://your-domain.com/api/billing/usage \
  -H "Authorization: Bearer TOKEN"

# Create checkout
curl -X POST https://your-domain.com/api/billing/create-checkout \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"org_id":"ORG_ID","price_id":"price_xxx"}'
```

## Error Responses

All errors return RFC 7807 Problem Details:

```json
{
  "type": "about:blank",
  "title": "Validation failed",
  "status": 422,
  "detail": "body -> field required",
  "instance": "/api/agents"
}
```

## Rate Limits

- Global: 60 requests/minute (configurable via `AIOS_RATE_LIMIT_PER_MINUTE`)
- Auth endpoints: 5 requests/minute per email
- File upload: 20 requests/minute

## Pagination

All list endpoints accept `limit` (1-200, default 50) and `offset` (default 0) query parameters.

## Webhooks

### Stripe
`POST /api/billing/stripe-webhook` — handles `checkout.session.completed`, `invoice.paid`, `customer.subscription.deleted`

### WhatsApp
`POST /webhook/whatsapp` — Meta WhatsApp Cloud API webhook

### Evolution
`POST /webhook/evolution` — Evolution API webhook
