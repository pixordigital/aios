# Runbook: WhatsApp Gateway

## Instance Quarantine (ban risk >85)
1. Dashboard /whatsapp → risk red → Pause outbound auto
2. Proxy rotate: POST /api/whatsapp/instances/{id}/proxy/rotate
3. Check Evolution logs: docker logs evolution

## Proxy Pool <30%
1. Check Squid: docker logs squid, curl http://squid:3128
2. Check IPv6: ip -6 addr show, test curl --interface 2a01:4f8:1c1a:924a::2 https://ifconfig.co
3. Rotate: POST /api/whatsapp/proxy/rotate/{id}

## Vault Sealed
1. vault status
2. vault operator unseal (3-of-5 Shamir)
3. Verify: vault read transit/keys/aios

## Voice MOS <3.5
1. Check Janus: curl http://janus:8088/janus/info
2. Check coturn: turnutils_uclient -v
3. Fallback: audio_only → voicemail

## LGPD DSR
1. POST /api/whatsapp/lgpd/dsr/access {phone_hash}
2. POST /api/whatsapp/lgpd/dsr/delete {phone_hash}
3. Verify SeaweedFS purge: s3cmd ls s3://aios-whatsapp/

## Disaster Recovery
- RTO 15m: docker compose up -d (same VPS, Hetzner snapshot)
- Vault backup: /vault/file + Shamir shares offline
