# ⚠️ Synthetic Product Test — not customer evidence

## 1. Run information

- Product / version: AIOS; version not exposed by the public page
- Target / start: `http://127.0.0.1:8777/`, logged out
- Run id: `2026-11-17-founder-operator-01`
- Mode: `test` (first member of an isolated synthetic prospect panel)
- Persona: [founder-operator.yaml](persona-founder-operator.yaml)
- Scenario: [scenario-business-prospect-access.yaml](scenario-business-prospect-access.yaml)
- Environment: Chrome, Linux, 1440×900, stable local connection
- Interaction fidelity: `visual`
- Allowed state changes: none
- Limitations: Assumption-based persona; no test account; test stopped at login; no authenticated business workflow tested.

## 2. Frozen user contract

| Item | Contract | Source |
|---|---|---|
| Goal | Find a legitimate way to start an AIOS evaluation for the business | Scenario assumption |
| Current approach | Review new leads, reply manually, track follow-up in an inbox/spreadsheet | Explicit persona assumption |
| Proficiency | Medium business-domain and digital proficiency | Neutral assumption, not inferred from age or role |
| Reading / navigation | Scan headings first; choose familiar setup labels | Persona configuration |
| Action / recovery budget | 6 actions; 1 recovery | Persona configuration |
| Help seeking | Use one visible in-product help/contact path if present | Persona configuration |
| Risk / privacy | Do not invent credentials, enter real customer data, connect channels, or alter data | User safety boundary |

## 3. Task result

- Terminal state: `BLOCKED`
- Success condition reached: no
- Actions used: 3
- Recovery attempts used: 1
- Stop point: Login page displayed “Cadastros temporariamente fechados” (sign-ups temporarily closed). No visible contact or demo route appeared on that page.
- Result: The prospect could inspect the public marketing page but could not create an account or evaluate the product.

## 4. User action log

| Step | State | Visible cue | Expected result | Action | Observed result | Short reaction | Evidence |
|---:|---|---|---|---|---|---|---|
| 1 | ORIENT | Landing page headline: “Crie & Gerencie Agentes de IA e Times para seu Negócio”; visible “Criar meu primeiro agente” CTA | Find a way to start evaluating an agent | Open public entry page | Marketing page describes agent and team capabilities; CTA is visible | “Parece feito para o meu negócio; vou tentar começar.” | [Step 1](founder-step-01.png) |
| 2 | ATTEMPT | “Criar meu primeiro agente →” | Begin setup or reach account creation | Click CTA | Page scrolls to an explanatory section at `#agentes`; no setup or account form opens | “A página explica, mas ainda não comecei nada.” | [Step 2](founder-step-02.png) |
| 3 | RECOVER | Header “Abrir Dashboard” | Reach a workspace or an evaluation path | Click header link | Login screen appears with email/password fields and “Cadastros temporariamente fechados” | “Preciso de acesso; não consigo avaliar por conta própria.” | [Step 3](founder-step-03.png) |

## 5. Synthetic user debrief

> Eu queria descobrir se consigo testar um agente para acompanhar leads. O botão de criar meu primeiro agente só me levou a mais explicações; o dashboard pediu uma conta, e o cadastro está fechado. Eu pararia aqui e perguntaria ao fornecedor se existe convite ou demonstração.

## 6. Findings

| ID | Type | Finding | Evidence | Task impact | Severity | Persona field | Confidence |
|---|---|---|---|---|---|---|---|
| F-01 | OBSERVED | The “Criar meu primeiro agente” CTA scrolls to a product explanation rather than starting account or agent setup. | Steps 1–2 | Adds a detour for a prospect trying to begin setup. | S1 MINOR | `goals.primary`; `behavior.navigation` | MEDIUM |
| F-02 | OBSERVED | A new prospect reaches login, where the page says registration is temporarily closed; no contact/demo route is visible there. | Step 3 | Blocks this prospect’s evaluation task. This may be intentional for the current internal-tool direction; it is not treated as a defect against that direction. | S3 BLOCKER for this external-prospect task | `context.product_relationship`; `goals.success_definition` | MEDIUM |

## 7. Improvement hypothesis

| Finding | Change hypothesis | Expected observable effect | Human validation needed |
|---|---|---|---|
| F-01 | If external prospects are an intended audience, make the CTA’s destination match its setup wording, or label it as an informational section. | A prospect can predict whether the CTA starts setup or explains features. | Yes; confirm intended audience and test with real prospects. |
| F-02 | If external evaluations are intended, expose the supported invitation, demo, or contact path. If AIOS is internal-only, make that status clear before the setup CTA. | Prospects can identify whether they are eligible and what to do next. | Yes; this depends on product strategy, which a synthetic user cannot decide. |

## 8. Limits and real-user follow-up

- This run shows what one assumption-based prospect encountered on one public journey.
- It does not establish demand, willingness to pay, product-market fit, trust, or how real businesses behave.
- It did not test an authenticated account, agent setup, channel connection, approval, or business outcome.
- Ask intended business users: “What would you expect ‘Create my first agent’ to do?” and “What access path would let you evaluate an AI agent without risking a real customer interaction?”
- Recommended follow-up: moderated usability sessions with real target businesses, only if external customers are in scope. For the current internal-tool direction, evaluate the workflow with intended internal operators instead.
