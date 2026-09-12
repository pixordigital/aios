# Template WhatsApp — HITL 131047 (Fora da janela 24h)

**Nome:** `aios_reengajamento_1`  
**Categoria:** `Utility`  
**Idioma:** `pt_BR`  
**Status:** Pendente de aprovação no WhatsApp Manager

## Corpo (pt_BR)

```
Olá {{1}}, aqui é da {{2}}. Você conversou sobre {{3}} — posso te ajudar a retomar de onde parou?
```

**Exemplo preenchido:**
```
Olá Carla, aqui é da Pixor AIOS. Você conversou sobre Agendamento Real — posso te ajudar a retomar de onde parou?
```

**Parâmetros:**
- `{{1}}` = `nome` (ex: Carla)
- `{{2}}` = `empresa` (ex: Pixor AIOS)
- `{{3}}` = `assunto` (ex: Agendamento Real)

**Botões:**
- `Continuar` (quick reply)
- `Falar com humano` (quick reply)

**Categoria Utility:** Vinculado a transação/utilidade (agendamento, suporte), aprova em 1-2 dias. Não é Marketing (que precisa opt-in e demora).

## Como submeter (1x)

1. **WhatsApp Manager** → https://business.facebook.com/wa/manage/message-templates
2. **Criar template** → Categoria `Utility` → Idioma `pt_BR` → Nome `aios_reengajamento_1`
3. Cole corpo acima com `{{1}}`, `{{2}}`, `{{3}}`
4. Adicione 2 botões Quick Reply: `Continuar` e `Falar com humano`
5. Envie para aprovação → aguarde 1-2 dias
6. Quando aprovado, teste via `POST /api/skills/import-url` com `whatsapp_template` tool

## Uso no AIOS (autônomo)

```python
# Quando Evaluator detecta 131047 (fora da janela 24h)
# Trial 1: send text → 131047
# Reflection: "Fora da janela 24h, trocar para template"
# Trial 2: http_request type:template
{
  "tool": "whatsapp_template",
  "template": "aios_reengajamento_1",
  "language": "pt_BR",
  "components": [
    {"type": "body", "parameters": [
      {"type": "text", "text": "{{nome}}"},
      {"type": "text", "text": "{{empresa}}"},
      {"type": "text", "text": "{{assunto}}"}
    ]}
  ]
}
```

**Fallback:** Se template ainda não aprovado (131047 de novo), **escalona para humano** (`PendingAction`) — não envia `hello_world`.

## Teste

```bash
curl -X POST https://seu-dominio.com/api/skills/import-url \
  -H "Authorization: Bearer TOKEN" \
  -d '{"url": "https://raw.githubusercontent.com/pixor/aiso/main/docs/templates/whatsapp_131047_template.md", "agent_id": "..."}'
```

