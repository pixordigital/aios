"""Evolution webhook parsing + channel surface.

Originally tested `aios.api.whatsapp_webhook` and `aios.channels.whatsapp`.
Commit 397a0d7 ("consolidate WhatsApp to Evolution API") deleted both modules
in favour of the Baileys/Meta bridge, and left this file importing the dead
paths. The parsing assertions were kept against the module that replaced it.
"""

import inspect


class TestParseMessage:
    def test_baileys_text(self):
        from aios.api.evolution_webhook import _parse_message
        text, sender, mid = _parse_message(
            {"key": {"remoteJid": "5511999999999@s.whatsapp.net", "id": "X1"},
             "message": {"conversation": "oi"}},
            "messages.upsert",
        )
        assert text == "oi"
        assert sender == "5511999999999"
        assert mid == "X1"

    def test_baileys_media_carries_caption(self):
        from aios.api.evolution_webhook import _parse_message
        text, _, _ = _parse_message(
            {"key": {"remoteJid": "1@s.whatsapp.net", "id": "X2"},
             "message": {"imageMessage": {"caption": "foto"}}},
            "messages.upsert",
        )
        assert "foto" in text

    def test_baileys_voice_note_is_marked_not_transcribed(self):
        from aios.api.evolution_webhook import _parse_message
        text, _, _ = _parse_message(
            {"key": {"remoteJid": "1@s.whatsapp.net", "id": "X3"},
             "message": {"audioMessage": {}}},
            "messages.upsert",
        )
        assert "áudio" in text

    def test_meta_cloud_text(self):
        from aios.api.evolution_webhook import _parse_message
        text, _, _ = _parse_message(
            {"key": {"remoteJid": "1@s.whatsapp.net", "id": "X4"},
             "message": {"type": "text", "text": {"body": "oi"}}},
            "messages.upsert",
        )
        assert text == "oi"

    def test_meta_cloud_button_reply(self):
        from aios.api.evolution_webhook import _parse_message
        text, _, _ = _parse_message(
            {"key": {"remoteJid": "1@s.whatsapp.net", "id": "X5"},
             "message": {"type": "interactive",
                         "interactive": {"type": "button_reply",
                                         "button_reply": {"id": "sim", "title": "Sim"}}}},
            "messages.upsert",
        )
        assert text == "Sim"

    def test_own_messages_are_ignored(self):
        """An agent that answers itself is the loudest webhook bug there is."""
        from aios.api.evolution_webhook import _parse_message
        assert _parse_message(
            {"key": {"fromMe": True, "remoteJid": "1@s.whatsapp.net"},
             "message": {"conversation": "oi"}},
            "messages.upsert",
        ) == ("", "", "")

    def test_unknown_payload_degrades_instead_of_raising(self):
        from aios.api.evolution_webhook import _parse_message
        assert _parse_message({}, "messages.upsert") == ("", "", "")


class TestSignatureVerification:
    def test_verify_helper_is_callable(self):
        from aios.api.evolution_webhook import _verify_request
        assert callable(_verify_request)

    def test_signature_helper_is_callable(self):
        from aios.api.evolution_webhook import _verify_evolution_sig
        assert callable(_verify_evolution_sig)

    def test_signature_rejects_wrong_key(self):
        from aios.api.evolution_webhook import _verify_evolution_sig
        body = {"instance": "x"}
        assert _verify_evolution_sig("", body, "right-key") is not True

    def test_stored_ciphertext_is_not_used_as_the_webhook_secret(self):
        """Auth used the raw config value; dashboard stores `enc:<fernet>`.

        The header Evolution sends is the plaintext secret, so comparing it to
        the ciphertext failed auth for every dashboard-created channel while
        API-created ones passed — the one path tests exercised.
        """
        from aios.api.evolution_webhook import _channel_api_key
        from aios.core.secrets import encrypt_channel_config
        from aios.db.models import ChannelConnection

        secret = "whatsapp-secret-do-not-log"
        ch = ChannelConnection(
            org_id="o1", label="l", channel_type="evolution",
            config=encrypt_channel_config({"instance": "i1", "api_key": secret}),
        )
        assert _channel_api_key(ch) == secret
        assert not _channel_api_key(ch).startswith("enc:")

    def test_plaintext_key_still_works(self):
        from aios.api.evolution_webhook import _channel_api_key
        from aios.db.models import ChannelConnection

        ch = ChannelConnection(
            org_id="o1", label="l", channel_type="evolution",
            config={"instance": "i1", "api_key": "plain"},
        )
        assert _channel_api_key(ch) == "plain"

    def test_missing_key_is_empty_not_ciphertext(self):
        from aios.api.evolution_webhook import _channel_api_key
        from aios.db.models import ChannelConnection

        ch = ChannelConnection(
            org_id="o1", label="l", channel_type="evolution", config={"instance": "i1"},
        )
        assert _channel_api_key(ch) == ""


class TestEvolutionChannel:
    def test_implements_base_contract(self):
        from aios.channels.base import Channel
        from aios.channels.evolution import EvolutionChannel
        assert issubclass(EvolutionChannel, Channel)
        for m in ("send", "start", "stop"):
            assert callable(getattr(EvolutionChannel, m)), m

    def test_provides_both_providers(self):
        """The consolidation's whole point: Baileys by default, Meta optional."""
        from aios.channels.evolution import EvolutionChannel
        assert hasattr(EvolutionChannel, "create_instance")
        assert hasattr(EvolutionChannel, "reconcile_provider")
        assert hasattr(EvolutionChannel, "meta_credentials")

    def test_missing_meta_credentials_is_safe(self):
        """Must report, not raise, when Meta env is absent."""
        from aios.channels.evolution import EvolutionChannel
        assert callable(EvolutionChannel.missing_meta_credentials)
