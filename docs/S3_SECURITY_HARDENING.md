# S3 Security Hardening (C9)

## Overview
This document describes the S3 security hardening implemented to meet Enterprise requirements for data protection and ransomware resilience.

## Features Implemented

### 1. Server-Side Encryption (SSE-S3)
- **Enabled by default**: All objects uploaded to S3 are encrypted at rest using AES-256
- **Configuration**: `AIOS_S3_SSE_ENABLED=true` (default)
- **Implementation**: `ServerSideEncryption: "AES256"` header on all `put_object` calls
- **Compliance**: Meets encryption-at-rest requirements for BAA/SOC2

### 2. Bucket Versioning
- **Enabled by default**: All object versions are retained
- **Configuration**: `AIOS_S3_VERSIONING_ENABLED=true` (default)
- **Protection**: Ransomware cannot permanently delete files — previous versions recoverable
- **Implementation**: `put_bucket_versioning` with `Status: "Enabled"`

### 3. Object Lock (Optional)
- **Configuration**: `AIOS_S3_OBJECT_LOCK_ENABLED=false` (default, requires bucket created with ObjectLockEnabled)
- **Use case**: Compliance/WORM requirements for regulated industries
- **Implementation**: `put_object_lock_configuration` with `ObjectLockEnabled: "Enabled"`

## Configuration

```bash
# Required for S3 backend
AIOS_STORAGE_BACKEND=s3
AIOS_S3_BUCKET=your-bucket
AIOS_S3_ACCESS_KEY=your-access-key
AIOS_S3_SECRET_KEY=your-secret-key
AIOS_S3_ENDPOINT=https://your-s3-endpoint  # Optional (R2, MinIO, Supabase)
AIOS_S3_REGION=us-east-1

# Security hardening (all enabled by default)
AIOS_S3_SSE_ENABLED=true
AIOS_S3_VERSIONING_ENABLED=true
AIOS_S3_OBJECT_LOCK_ENABLED=false  # Requires bucket with ObjectLockEnabled at creation
```

## Cloud Provider Specifics

### Cloudflare R2
- SSE-S3: Supported (AES256)
- Versioning: Supported
- Object Lock: Not supported
- Endpoint: `https://<account-id>.r2.cloudflarestorage.com`

### Supabase Storage
- SSE-S3: Supported (AES256)
- Versioning: Supported via Postgres WAL
- Object Lock: Not supported
- Endpoint: `https://<project-ref>.supabase.co/storage/v1/s3`

### MinIO
- SSE-S3: Supported (AES256, SSE-KMS)
- Versioning: Supported
- Object Lock: Supported (with MinIO GOVERNANCE/COMPLIANCE modes)
- Endpoint: `http://minio:9000`

### AWS S3
- SSE-S3: Supported (AES256, SSE-KMS, SSE-C)
- Versioning: Supported
- Object Lock: Supported (with bucket ObjectLockEnabled at creation)
- Endpoint: `https://s3.<region>.amazonaws.com`

## Verification

### Check SSE is Working
```bash
# Upload a test file
aws s3 cp test.txt s3://your-bucket/test.txt

# Verify encryption
aws s3api head-object --bucket your-bucket --key test.txt
# Should show: "ServerSideEncryption": "AES256"
```

### Check Versioning
```bash
aws s3api get-bucket-versioning --bucket your-bucket
# Should show: {"Status": "Enabled"}
```

### Enable Versioning (if not auto-enabled)
```bash
aws s3api put-bucket-versioning \
    --bucket your-bucket \
    --versioning-configuration Status=Enabled
```

## Recovery from Ransomware

If ransomware encrypts/deletes objects:
1. List object versions: `aws s3api list-object-versions --bucket your-bucket --prefix org-id/`
2. Identify last clean version
3. Restore: `aws s3api copy-object --bucket your-bucket --copy-source your-bucket/key?versionId=VERSION_ID --key key`

## Monitoring

The storage module logs SSE status on every upload:
```
INFO Saved s3://bucket/org-id/abc123.pdf (1024 bytes, SSE=True)
```

## Compliance Notes

| Requirement | SSE-S3 | Versioning | Object Lock |
|-------------|--------|------------|-------------|
| BAA (HIPAA) | ✅ Required | ✅ Recommended | Optional |
| SOC 2 | ✅ Required | ✅ Recommended | Optional |
| PCI DSS | ✅ Required | ✅ Required | Optional |
| GDPR | ✅ Recommended | ✅ Recommended | Optional |

## Migration from Non-Versioned Bucket

If you have an existing bucket without versioning:
1. Enable versioning (irreversible)
2. Existing objects get `null` version ID
3. New uploads get version IDs
4. Consider lifecycle rules to manage version count/costs

```json
{
  "Rules": [
    {
      "ID": "expire-old-versions",
      "Status": "Enabled",
      "NoncurrentVersionExpiration": {"NoncurrentDays": 90}
    }
  ]
}
```