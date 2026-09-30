# S3 Object Put & Versioning

> 13 nodes · cohesion 0.23

## Key Concepts

- **S3Storage** (12 connections) — `aios/core/storage.py`
- **._get_client()** (6 connections) — `aios/core/storage.py`
- **.enable_object_lock()** (3 connections) — `aios/core/storage.py`
- **.enable_versioning()** (3 connections) — `aios/core/storage.py`
- **._put_args()** (3 connections) — `aios/core/storage.py`
- **.save()** (3 connections) — `aios/core/storage.py`
- **.delete()** (2 connections) — `aios/core/storage.py`
- **.read()** (2 connections) — `aios/core/storage.py`
- **Additional arguments for put_object (SSE, etc.).** (1 connections) — `aios/core/storage.py`
- **Enable bucket versioning for ransomware protection.** (1 connections) — `aios/core/storage.py`
- **Enable Object Lock for compliance (requires bucket created with…** (1 connections) — `aios/core/storage.py`
- **S3-compatible storage (Supabase Storage, Cloudflare R2, MinIO). Security…** (1 connections) — `aios/core/storage.py`
- **.__init__()** (1 connections) — `aios/core/storage.py`

## Relationships

- [Storage Backends](Storage_Backends.md) (3 shared connections)

## Source Files

- `aios/core/storage.py`

## Audit Trail

- EXTRACTED: 21 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*