# ⚠️ Synthetic Product Test — not real user evidence

## 1. Run information

- Product / version: AIOS / version not exposed in public UI
- Target / start state: `http://127.0.0.1:8777/`; public landing page, logged out, new prospect
- Date / run id: 2026-11-17 / `sales-manager-2026-11-17`
- Mode: test
- Persona file: `product-feedback/2026-11-17/persona-sales-manager.yaml`
- Scenario file: `product-feedback/2026-11-17/scenario-business-prospect-access.yaml`
- Device / viewport / network: Desktop, browser capture was 1280×720; persona contract specifies 1365×768; stable network assumed from scenario
- Interaction fidelity: visual
- Allowed state changes: none; page navigation and scrolling only
- Test limitations: One synthetic session. No account creation, credential entry, contact submission, external messaging, source inspection, or external search. The full landing page was not exhaustively reviewed.

## 2. Frozen user contract

| Item | Value | Source |
|---|---|---|
| Goal | Find a legitimate signup, demo, or contact route to begin a business evaluation | `persona.goals.primary`, `persona.goals.success_definition`; scenario task |
| Current workflow | Shared inbox or CRM review, manual rep assignment, follow-up check in team report | `persona.status_quo.current_workflow` (assumption) |
| Work / digital proficiency | Medium domain and digital proficiency; recommender evaluating for a business owner | `persona.context`, `persona.behavior` |
| Reading / navigation | Skim, first scan about six seconds, familiar labels first | `persona.behavior.attention`, `persona.behavior.navigation` |
| Action / recovery budget | Maximum 5 actions, 1 recovery; one backtrack allowed | `persona.behavior.patience`, `persona.behavior.navigation` |
| Help seeking | One visible in-product help/contact route may be used | `persona.behavior.help_seeking` |
| Risk / privacy | Low risk tolerance; no customer data, credentials, live channel connection, external message, payment, or business data change | `persona.behavior.trust`, `persona.boundaries` |

Assumptions remain those declared by the persona: the workflow and business context are scenario assumptions, not interview evidence. The local app was reachable; product version and network conditions were not independently established.

## 3. Task result

- Terminal state: **BLOCKED**
- Success condition reached: no
- Actions used: 4 of 5 (two downward scrolls, one visible CTA click, one further downward scroll)
- Recovery attempts used: 0 of 1
- Stop point: After the landing page hero and beginning of “01 / Plataforma de Agentes”; no prospect signup, demo, or contact route was visible in the inspected portion. The visible UI framed the product as an internal/self-hosted platform and exposed agent/dashboard controls.
- Result summary: **TEST BLOCKER:** This new prospect could not identify a visible evaluation-access route in the portion inspected. No credentials were available, so the session stopped without trying an account flow or changing state.

## 4. User behavior log

| Step | State | Visible cue | Expected result | Action | Observed result | Short reaction | Evidence |
|---:|---|---|---|---|---|---|---|
| 1 | ORIENT | Landing hero: “Crie & Gerencie Agentes de IA e Times para seu Negócio”; header includes “Control Center” and “Abrir Dashboard” | Get a quick sense of whether this is for a business prospect | Skim the opening screen | Portuguese hero describes creating/managing AI agents and teams; no signup, demo, or contact route visible on this screen | “Looks like an agent platform. I don’t see how to evaluate it yet.” | `sales-manager-step-00.png` |
| 2 | ATTEMPT | The hero remains prominent; no access link appears in the first screen | Find a clear next step lower on the page | Scroll down | Hero details include a “Criar meu primeiro agente” button, “Governança”, “Customização”, and the statement “Ferramenta interna · RLS por Organização · Self-hosted no seu VPS · Suíte com ARVO” | “This sounds like something we run internally. Maybe the button is the way in.” | `sales-manager-step-01.png`, `sales-manager-step-02.png` |
| 3 | ATTEMPT | Visible “Criar meu primeiro agente →” CTA | See whether it opens a route to evaluate the product | Click the visible CTA once | No prospect-access page or signup appeared; the same landing page remained visible, with the viewport positioned around the CTA/next section | “That didn’t show me how to get access.” | `sales-manager-step-03.png` |
| 4 | ATTEMPT | Section heading “01 / PLATAFORMA DE AGENTES” and “Crie agentes, monte times e escale com governança” | Check the next visible section for a demo/contact route | Scroll down | The section describes API/dashboard lifecycle and 21 blueprints; visible content still offers no prospect signup, demo request, or contact route | “I can see what it does, but I still can’t start a safe evaluation.” | `sales-manager-step-04.png` |

## 5. Persona debrief

> I wanted a safe way to evaluate this with the team before connecting any sales systems. I saw how the platform creates agents and that it is described as internal and self-hosted, but I didn’t find a signup, demo, or contact route in the part I checked. I’d ask the business owner whether they already have access before going further.

## 6. Findings

| ID | Type | Finding | Evidence | Task impact | Severity | Persona field | Confidence |
|---|---|---|---|---|---|---|---|
| F-01 | OBSERVED | In the inspected landing page portion, no visible signup, demo request, or contact route surfaced; the visible CTA was for creating a first agent, and the page described itself as an internal, self-hosted tool. | Steps 1–4; `sales-manager-step-00.png` to `sales-manager-step-04.png` | Prospect could not begin the stated safe team evaluation from the visible cues inspected; ended BLOCKED under the scenario stop rule. | S3 BLOCKER for this task/session | `persona.goals.success_definition`; `persona.behavior.patience.quit_triggers`; `persona.boundaries.prior_knowledge` | MEDIUM (direct observation in one synthetic session; only part of the landing page inspected) |

## 7. Improvement hypothesis

| Finding | Change hypothesis | Expected observable effect | Human validation needed |
|---|---|---|---|
| F-01 | If prospects are eligible to evaluate AIOS, make the intended evaluation or contact route visible from the public landing page. | A new prospect can identify a legitimate next step without credentials or connecting a live system. | Yes; validate eligibility and wording with the product owner, then observe new prospects attempting this task. |

## 8. Test limits and real-user follow-up

- What this run can tell us: In this single visual synthetic session, the inspected landing page portion did not reveal a prospect evaluation route; the visible content emphasized agent creation, governance, and self-hosting.
- What this run cannot tell us: Whether an access route exists elsewhere on the full page or via an untested navigation item; whether prospects are eligible for evaluation; actual user comprehension, demand, emotions, or conversion impact; access controls or handoff behavior inside an account.
- Questions for real users: Where would you look for a safe product evaluation? What information do you need before connecting a CRM or messaging channel?
- Recommended method: Moderated usability test with new business prospects, using a test workspace and no live customer data.
