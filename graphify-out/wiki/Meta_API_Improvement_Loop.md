# Meta API Improvement Loop

> 11 nodes · cohesion 0.25

## Key Concepts

- **meta.py** (18 connections) — `aios/api/meta.py`
- **apply_improvement()** (5 connections) — `aios/api/meta.py`
- **run_eval()** (5 connections) — `aios/api/meta.py`
- **ApplyRequest** (3 connections) — `aios/api/meta.py`
- **EvalRequest** (3 connections) — `aios/api/meta.py`
- **eval_history()** (2 connections) — `aios/api/meta.py`
- **get_suggestions()** (2 connections) — `aios/api/meta.py`
- **BaseModel** (2 connections)
- **post** (2 connections)
- **Meta agent API — eval history, run eval, apply improvement.** (1 connections) — `aios/api/meta.py`
- **Score a response against rubric and generate suggestions.** (1 connections) — `aios/api/meta.py`

## Relationships

- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (5 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (5 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (1 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)

## Source Files

- `aios/api/meta.py`

## Audit Trail

- EXTRACTED: 25 (83%)
- INFERRED: 5 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*