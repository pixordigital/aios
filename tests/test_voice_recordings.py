"""Voice recording tenant-scope tests."""


class TestVoiceRecordingTenantScope:
    async def test_cross_tenant_voice_recording_access_records_metric(self, auth_client, test_db_session, second_org):
        from sqlalchemy import select

        from aios.db.models import VoiceRecording
        from aios.governance.security import SecurityEvent

        other = VoiceRecording(
            org_id=second_org.id,
            call_sid="CA-other-1",
            from_number="+5511000000000",
            to_number="+5511999999999",
            direction="inbound",
            duration_seconds=12,
        )
        test_db_session.add(other)
        await test_db_session.commit()
        await test_db_session.refresh(other)

        cases = [
            ("get", f"/api/voice/recordings/{other.id}", None, "voice_recordings.api.get"),
            ("get", f"/api/voice/recordings/{other.id}/audio", None, "voice_recordings.api.audio"),
            ("post", f"/api/voice/recordings/{other.id}/transcribe", None, "voice_recordings.api.transcribe"),
        ]
        for method, path, body, source in cases:
            req = getattr(auth_client, method)
            resp = await req(path, json=body) if body is not None else await req(path)
            assert resp.status_code == 404, (path, resp.text)

        rows = (
            await test_db_session.execute(
                select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
            )
        ).scalars().all()
        for _, _, _, source in cases:
            assert any(
                e.payload.get("metric") == "cross_tenant_block"
                and e.payload.get("resource_type") == "VoiceRecording"
                and e.payload.get("resource_org_id") == second_org.id
                and e.payload.get("recording_id") == other.id
                and e.source == source
                for e in rows
            ), source
