# Client Onboarding Checklist

## For Each New Client

### Pre-Deployment
- [ ] Client provides VPS IP + SSH access
- [ ] Client provides domain (or use IP)
- [ ] Client provides LLM API key (OpenRouter recommended)
- [ ] Client provides Stripe keys (if billing enabled)

### Deployment
```bash
# Deploy to client VPS
./deploy/client-deploy.sh "ClientName" "admin@client.com" "your-master-key"
```

### Post-Deployment
- [ ] Verify health: `curl http://CLIENT_IP:8777/health`
- [ ] Open dashboard: `http://CLIENT_IP:8777/dashboard`
- [ ] Login with admin credentials
- [ ] Create first agent
- [ ] Connect channel (WhatsApp/Email/Web)
- [ ] Test agent responds

### Optional Configuration
- [ ] Set SMTP for email features
- [ ] Set Stripe for billing
- [ ] Set Google/GitHub OAuth
- [ ] Set Sentry for error tracking
- [ ] Configure HTTPS (Cloudflare or Caddy)

### Client Training
- [ ] Show dashboard overview
- [ ] Explain agent creation workflow
- [ ] Explain channel connection
- [ ] Explain governance config (autonomy, tool limits)
- [ ] Share API docs link
- [ ] Share support email

### Monitoring
- [ ] Add client to fleet dashboard
- [ ] Set up health monitoring
- [ ] Schedule weekly check-in

## Client Credentials Template

```
AIOS INSTANCE: ClientName
URL: http://IP:8777
DASHBOARD: http://IP:8777/dashboard
ADMIN: admin@client.com
PASSWORD: <generated>
MASTER_KEY: <generated>

SAVE THIS SECURELY — credentials cannot be recovered.
```

## Support Contacts

- Technical issues: support@aios.dev
- Billing: billing@aios.dev
- Emergency: emergency@aios.dev
