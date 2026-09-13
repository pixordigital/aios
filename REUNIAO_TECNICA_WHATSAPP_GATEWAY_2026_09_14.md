# Reunião Técnica: AIOS WhatsApp Gateway — Build vs Buy vs Hybrid

**Data:** 2026-09-14 10:00 — 12:00  
**Participantes:**
- **SWE Lead** (Arquiteto Python/FastAPI, dono do código)
- **WhatsApp Specialist** (Conhece Baileys, Evolution API, Cloud API, anti-ban)
- **VPS/Server Specialist** (Infra, Docker, K8s, rede, proxy, custos)
- **Tech Specialist** (Decisões de arquitetura, trade-offs, custos, compliance)

**Objetivo:** Decidir se **construímos** o AIOS WhatsApp Gateway próprio ou **mantemos/estendemos** Evolution API. Analisar viabilidade, custos, alternativas gratuitas/self-hosted.

---

## 1. Contexto Atual

| Item | Status |
|------|--------|
| **Evolution API em produção** | v2.3.7, Baileys + Cloud API, multi-tenant, webhook funcionando |
| **AIOS Core** | Python/FastAPI, agentes, CRM, flows, sandbox, voice (Kokoro) |
| **Dor atual** | Ban rate alto (Baileys), sem anti-ban sistemático, LGPD manual, sem voice nativo |
| **Meta** | Gateway próprio com anti-ban robusto, LGPD nativo, voice WebRTC, custos controlados |

---

## 2. Posições Iniciais

### **SWE Lead**
> "Quero código próprio (Python) para integrar nativamente com AIOS (agents, CRM, flows). Evolution API é Node.js — adiciona complexidade operacional (2 runtimes, 2 deploys, 2 stacks de monitoramento). Se construirmos wrapper Python + anti-ban middleware, ganhamos controle total e eliminamos polyglot."

### **WhatsApp Specialist**
> "Evolution API já faz o trabalho pesado: Baileys wrapper, Cloud API, instâncias, QR, webhooks. Reescrever Baileys em Python é **suicídio** — 50k+ linhas, protobuf, Noise protocol, manutenção constante. **Não reescrevam Baileys**. Usem Evolution API como *engine* e construam **camada de orquestração + anti-ban + LGPD + voice** em Python."

### **VPS/Server Specialist**
> "Evolution API já roda em container (já temos). Adicionar gateway Python = +1 container, +1 porta, +1 health check. **Proxy pool self-hosted (Squid)** é barato (~$50/mês para 5 VPS). **BrightData** é o custo real (~$500-1000/mês). **Janus** para WebRTC = +1 VPS. **Vault/MinIO** = +2-3 VPS. Total estimado: **$800-1500/mês** vs Evolution API only (~$200/mês)."

### **Tech Specialist**
> "Trade-off: **Controle vs Custo vs Tempo**.
> - **Build completo (rewrite Baileys)**: 12-18 meses, risco altíssimo, **NÃO**.
> - **Wrapper + orquestração (recomendado WhatsApp Specialist)**: 14 semanas Phase A, risco médio, custo +$600-1300/mês.
> - **Stay Evolution API only**: Zero dev, custo baixo, mas **sem anti-ban, sem LGPD nativo, sem voice, sem migration advisor**.
> - **Híbrido ideal**: Evolution API como *engine* (não mexer) + Python Gateway como *control plane* (anti-ban, LGPD, voice, proxy, migration advisor)."

---

## 3. Análise de Viabilidade: Build vs Buy

### **Opção A: Ficar só com Evolution API (Status Quo + Config)**

| Prós | Contras |
|------|---------|
| Zero dev time | Ban rate 15-30% (Baileys) — **perde contas** |
| Custo infra mínimo (~$200/mês) | LGPD manual — **risco legal** |
| Já funciona, estável | Sem voice nativo — **perde deals Enterprise** |
| Cloud API já disponível | Sem migration advisor — **migração cega** |
| | Sem proxy pool — **IPs queimados** |
| | Sem anti-ban sistemático — **reativo, não proativo** |

**Veredito:** ❌ **Não aceitável** para produto enterprise 2026.

---

### **Opção B: Build Completo (Rewrite Baileys em Python)**

| Prós | Contras |
|------|---------|
| Controle total do protocolo | 50k+ linhas TypeScript → Python |
| Zero dependência externa | Protobuf + Noise protocol + Multi-device |
| | Manutenção contínua (WhatsApp muda protocol) |
| | 12-18 meses, 2-3 engenheiros full-time |
| | Risco de ban **maior** no início (imaturidade) |

**Veredito:** ❌ **Suicídio técnico**. Não faça.

---

### **Opção C: Wrapper + Orquestração (Recomendado) — "Evolution API as Engine, Python as Brain"**

```
┌─────────────────────────────────────────────────────────────┐
│                    AIOS WHATSAPP GATEWAY                    │
├─────────────────────────────────────────────────────────────┤
│  Python Gateway (FastAPI)                                   │
│  ├── Provider Abstraction → Evolution REST API              │
│  ├── Anti-Ban Middleware (7 layers)                         │
│  ├── Proxy Pool Manager (Hybrid)                            │
│  ├── LGPD Compliance Layer                                  │
│  ├── KMS (Envelope + Vault)                                 │
│  ├── Migration Advisor                                      │
│  └── Voice Orchestration → Janus WebRTC                     │
├─────────────────────────────────────────────────────────────┤
│  Evolution API (Node.js) — UNTOUCHED                        │
│  ├── Baileys Provider                                       │
│  ├── Cloud API Provider                                     │
│  ├── Instance Management                                    │
│  ├── QR/Pairing, Webhooks                                   │
└─────────────────────────────────────────────────────────────┘
```

| Prós | Contras |
|------|---------|
| Anti-ban nativo (7 layers) | +1 serviço (Python Gateway) |
| LGPD nativo (consent, DSR, audit) | +$600-1300/mês infra |
| Voice WebRTC nativo (Janus + Kokoro) | Complexidade operacional +1 |
| Migration Advisor inteligente | Curva de aprendizado Evolution REST |
| Proxy pool híbrido | BrightData custo variável |
| Código Python (mesmo stack AIOS) | Deploy duplo (Node + Python) |
| **14 semanas Phase A** | **BrightData = custo variável** |

**Veredito:** ✅ **Viável, recomendado, ROI claro.**

---

## 4. Análise de Custos: Otimização "Free/Self-Hosted"

| Componente | Pago (Atual) | Alternativa Free/Self-Hosted | Economia | Trade-off |
|------------|--------------|------------------------------|----------|-----------|
| **BrightData (Residential Proxy)** | $500-1000/mês | **Self-hosted 4G/5G modem farm** (Raspberry Pi + dongles) | ~$500-1000/mês | Setup complexo, manutenção física, escala limitada |
| | | **Proxy rotation via Tor** (gratuito) | ~$500-1000/mês | Lento, IPs queimados, **não recomendado para produção** |
| | | **Data center proxies (self-hosted VPS + Squid)** — Tier 2 only | ~$300-500/mês | Menos efetivo que residential, mas **viável como fallback** |
| **Vault (HCP/Cloud)** | $0.03/secret + $0.50/mês | **HashiCorp Vault self-hosted (Raft 3-node)** | ~$50-100/mês | Operação própria (unseal, backup, DR) |
| **MinIO (S3 compatível)** | S3 $0.023/GB | **MinIO self-hosted (4-node distributed, Governance mode)** | ~$20-50/mês | Storage local, backup próprio |
| **Janus WebRTC** | Managed ($200-500/mês) | **Janus self-hosted (Docker/K8s)** | ~$150-400/mês | Config WebRTC/ICE/STUN/TURN própria |
| **STUN/TURN Server** | Twilio/Plivo ($0.004/min) | **coturn self-hosted** | Variável | Precisa IPs públicos, cotas de banda |
| **Kokoro TTS** | API externa | **Já temos `voice-tts-kokoro:8880` self-hosted** | $0 | **Já resolvido** ✅ |

### **Cenários de Custo Mensal (Estimado)**

| Cenário | BrightData | Vault/MinIO/Janus Self-Hosted | VPS Proxy (Squid) | Total Estimado |
|---------|------------|-------------------------------|-------------------|----------------|
| **Full Paid (Baseline)** | $800 | $200 (managed) | $50 | **~$1050/mês** |
| **Hybrid (Recomendado)** | $500 (reduzido 50%) | $100 (self-hosted) | $50 | **~$650/mês** |
| **Maximum Savings** | $0 (modem farm futuro) | $50 (VPS only) | $50 | **~$100/mês** *(futuro)* |

**Recomendação:** **Hybrid** — BrightData 50% volume (apenas instâncias novas/alto risco) + Tier 2/3 self-hosted. Evolui para modem farm no Phase B.

---

## 5. Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| Evolution API breaking change | Média | Alto | Provider abstraction + version pin + CI compatibility matrix |
| BrightData aumenta preço | Alta | Médio | Tier 2/3 self-hosted pronto, modem farm roadmap |
| Ban wave massiva | Média | Alto | Auto-quarantine + proxy rotation + instance provisioning automático |
| Vault seal / key loss | Baixa | Crítico | Shamir backup (3-of-5) + DR test mensal |
| Janus WebRTC instável | Média | Médio | Fallback audio-only + monitoring MOS |
| LGPD audit failure | Baixa | Crítico | WORM logs + automated compliance tests |
| Engenheiro único (bus factor) | Alta | Alto | Documentação extensa + runbooks + ADRs |

---

## 6. Decisão: **VAMOS CONSTRUIR (Opção C — Hybrid)**

### **Escopo Phase A (14 semanas, GA)**

| Componente | Build | Usa Existente | Custo Adicional |
|------------|-------|---------------|-----------------|
| Provider Abstraction (Python) | ✅ | Evolution REST | Dev time |
| Anti-Ban Middleware (7 layers) | ✅ | — | Dev time |
| Proxy Pool (Hybrid) | ✅ | BrightData (50%) + Squid | $550/mês |
| LGPD Compliance | ✅ | — | Dev time |
| KMS (Vault + Envelope) | ✅ | Vault self-hosted | $50/mês |
| Migration Advisor | ✅ | — | Dev time |
| Voice (Janus + Kokoro) | ❌ **Phase B** | Kokoro pronto | $0 Phase A |
| API + Dashboard | ✅ | FastAPI + templates | Dev time |

**Custo Phase A:** ~$600/mês infra + 14 semanas dev (1 engenheiro)

---

## 7. Próximos Passos Imediatos

| Ação | Responsável | Prazo |
|------|-------------|-------|
| Abrir conta BrightData (trial) | WhatsApp Specialist | Hoje |
| Provisionar Vault (3-node Raft), MinIO (4-node Governance), Janus | VPS Specialist | Semana 1 |
| Escrever ADRs 001-007 + Threat Model | SWE Lead | Semana 1 |
| Iniciar `aios/core/whatsapp/provider/base.py` | SWE Lead | Semana 2 |
| Validar Evolution REST API endpoints necessários | WhatsApp Specialist | Semana 2 |
| Configurar Squid fleet (5 VPS) | VPS Specialist | Semana 3 |

---

## 8. Conclusão da Reunião

> **Consenso unânime:** **Build Hybrid (Opção C)**.
>
> - **Não reescrever Baileys** — Evolution API continua como engine.
> - **Python Gateway** = control plane (anti-ban, LGPD, proxy, migration, voice orchestration).
> - **Custo controlado** — Hybrid proxy (BrightData 50% + self-hosted), Vault/MinIO/Janus self-hosted.
> - **Phase A (14 sem)** = GA sem voice. **Phase B** = voice + ML anti-ban + compliance automation.
> - **Risco aceitável** — Evolution API estável, wrapper Python mesmo stack AIOS.

---

**Assinaturas:**

SWE Lead: _________________  WhatsApp Specialist: _________________  
VPS Specialist: _________________  Tech Specialist: _________________  
Data: 2026-09-14
