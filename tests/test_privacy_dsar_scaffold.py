"""DSAR/privacy scaffold tests.

Status: scaffold only. These mark expected DSAR/privacy capabilities that are
not fully implemented yet. Human-gated before turning into enforcing tests.

No production data. No destructive behavior.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="DSAR/privacy scaffold: human-gated implementation pending")


class TestDSARExportScaffold:
    def test_subject_scoped_export_endpoint_exists(self):
        """Expected: subject-scoped export, not only org-wide GET /api/org/export."""
        raise NotImplementedError

    def test_export_manifest_includes_scope_and_truncation(self):
        """Expected: manifest has systems checked, UTC timestamp, truncation/redaction, checksum."""
        raise NotImplementedError

    def test_export_excludes_secrets_and_credentials(self):
        """Expected: tokens/secrets/hashed credentials never exported in plaintext."""
        raise NotImplementedError


class TestDSARErasureScaffold:
    def test_subject_scoped_erasure_or_anonymization_exists(self):
        """Expected: subject-level DSAR erasure/anonymization; org-wide delete is not enough."""
        raise NotImplementedError

    def test_erasure_respects_legal_hold(self):
        """Expected: legal hold blocks deletion and records reason/evidence."""
        raise NotImplementedError

    def test_erasure_covers_derived_data(self):
        """Expected: messages, CRM, transcripts, docs, RAG chunks, embeddings, caches, analytics extracts, vendors."""
        raise NotImplementedError


class TestRetentionScaffold:
    def test_retention_policy_defined_per_category(self):
        """Expected: approved retention schedule per PII category."""
        raise NotImplementedError

    def test_retention_purge_job_dry_run(self):
        """Expected: dry-run report before any purge; tenant-scoped, audited."""
        raise NotImplementedError


class TestConsentLawfulBasisScaffold:
    def test_consent_receipt_model_exists(self):
        """Expected: subject/purpose/granted/timestamp/source/proof/version evidence."""
        raise NotImplementedError

    def test_processing_activity_approval_requires_human_review(self):
        """Expected: approved status gated by human review/evidence."""
        raise NotImplementedError

    def test_evaluate_processing_enforced_at_data_boundaries(self):
        """Expected: fail-closed enforcement at real processing boundaries for sensitive/new processing."""
        raise NotImplementedError
