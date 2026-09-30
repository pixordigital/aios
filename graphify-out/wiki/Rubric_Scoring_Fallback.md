# Rubric Scoring Fallback

> 14 nodes · cohesion 0.23

## Key Concepts

- **RubricManager** (11 connections) — `aios/core/rubric.py`
- **Rubric** (7 connections) — `aios/core/rubric.py`
- **._score_heuristic()** (5 connections) — `aios/core/rubric.py`
- **.score_response()** (4 connections) — `aios/core/rubric.py`
- **._score_with_llm()** (4 connections) — `aios/core/rubric.py`
- **.create()** (2 connections) — `aios/core/rubric.py`
- **.get()** (2 connections) — `aios/core/rubric.py`
- **.list()** (2 connections) — `aios/core/rubric.py`
- **.update_rubric()** (2 connections) — `aios/core/rubric.py`
- **Fallback: length + criterion keyword presence.** (1 connections) — `aios/core/rubric.py`
- **Manage rubrics and score responses against them.** (1 connections) — `aios/core/rubric.py`
- **Score a response against rubric criteria (0-10 each). Uses LLM if available,…** (1 connections) — `aios/core/rubric.py`
- **.delete()** (1 connections) — `aios/core/rubric.py`
- **.__init__()** (1 connections) — `aios/core/rubric.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)

## Source Files

- `aios/core/rubric.py`

## Audit Trail

- EXTRACTED: 23 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*