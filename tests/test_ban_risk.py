"""Ban-risk scoring and durable guard state.

The risk stub it replaces took four integers no caller ever supplied, so the
risk it produced was invented. These tests pin the properties that matter:
real signals move the score, noise does not, and advice matches severity.
"""

import pytest

from aios.core.whatsapp.anti_ban.risk import score_from_events
from aios.core.whatsapp.anti_ban.signals import looks_like_ban


class TestScoring:
    def test_no_signals_is_green(self):
        r = score_from_events({})
        assert r.score == 0
        assert r.level == "green"
        assert not r.quarantined

    def test_one_429_is_noise(self):
        """A single rate limit happens. It should not red-alert the number."""
        assert score_from_events({"http_429": 1}).score == 0

    def test_sustained_429_scores_up(self):
        assert score_from_events({"http_429": 5}).score > 0

    def test_ban_signal_is_max_weight(self):
        a = score_from_events({"ban_signal": 1})
        b = score_from_events({"http_429": 20})
        assert a.score > b.score
        assert "ban_signal" in a.drivers

    def test_score_is_capped(self):
        r = score_from_events({"ban_signal": 9999, "http_403": 9999, "http_429": 9999})
        assert r.score <= 100

    def test_one_repeating_signal_never_quarantines(self):
        """Repetition of one signal alone must not trip the quarantine.

        Design choice: a single noisy signal firing forever should not be able
        to auto-quarantine a number. Quarantine needs corroboration from more
        than one kind of evidence — a false quarantine costs a live channel.
        """
        for kind in ("ban_signal", "http_403", "http_429", "disconnect"):
            r = score_from_events({kind: 5000})
            assert r.quarantined is False, f"{kind} alone quarantined"

    def test_corroborating_signals_quarantine(self):
        r = score_from_events({"ban_signal": 20, "http_403": 20, "http_429": 20, "disconnect": 20})
        assert r.quarantined is True
        assert r.score >= 85

    def test_velocity_above_warmup_cap_adds_risk(self):
        ok = score_from_events({}, velocity_ratio=0.5)
        hot = score_from_events({}, velocity_ratio=2.0)
        assert hot.score > ok.score
        assert "velocity" in hot.drivers

    def test_velocity_at_cap_is_not_a_violation(self):
        assert "velocity" not in score_from_events({}, velocity_ratio=1.0).drivers

    def test_disconnected_counts(self):
        r = score_from_events({}, connected=False)
        assert "disconnected" in r.drivers
        assert r.score > 0

    def test_advice_ordered_by_severity(self):
        r = score_from_events({"http_429": 10, "ban_signal": 1})
        assert r.advice
        assert "Sinal de ban ativo" in r.advice[0]

    def test_every_driver_has_advice(self):
        r = score_from_events({"ban_signal": 2, "http_429": 9, "disconnect": 5, "opted_out": 30})
        assert len(r.advice) >= 3


class TestBanDetection:
    def test_403_with_ban_words_is_a_ban(self):
        assert looks_like_ban(403, "number is blocked")

    def test_403_without_ban_words_is_not_a_ban(self):
        """Malformed payload also returns 403. Crying wolf trains people to
        ignore the dashboard."""
        assert not looks_like_ban(403, "invalid request body")

    def test_429_is_never_a_ban(self):
        assert not looks_like_ban(429, "too many requests, rate limited")

    def test_200_is_never_a_ban(self):
        assert not looks_like_ban(200, "blocked field missing")

    def test_401_suspended_is_a_ban(self):
        assert looks_like_ban(401, "account suspended")


class TestQuarantineGate:
    """The send path blocks the whole instance on corroborated ban evidence.

    is_quarantined hits the DB (one grouped query); these pin the decision
    boundary by stubbing the feed, not the database.
    """

    @pytest.mark.asyncio
    async def test_quarantined_on_corroborated_evidence(self, monkeypatch):
        from aios.core.whatsapp.anti_ban import signals

        async def feed(org_id, instance, days=1):
            return {"ban_signal": 20, "http_403": 20, "http_429": 20, "disconnect": 20}

        monkeypatch.setattr(signals, "gather_counts", feed)
        assert await signals.is_quarantined("org", "inst") is True

    @pytest.mark.asyncio
    async def test_not_quarantined_on_noise(self, monkeypatch):
        from aios.core.whatsapp.anti_ban import signals

        async def feed(org_id, instance, days=1):
            return {"http_429": 1, "sent": 40}

        monkeypatch.setattr(signals, "gather_counts", feed)
        assert await signals.is_quarantined("org", "inst") is False

    @pytest.mark.asyncio
    async def test_fails_open_without_db(self, monkeypatch):
        """If the event feed is unreachable, sends proceed.

        Blocking all WhatsApp traffic on a telemetry outage would be worse
        than the risk it guards against. The score degrades to 0, not to fear.
        """
        from aios.core.whatsapp.anti_ban import signals

        async def feed(org_id, instance, days=1):
            return {}

        monkeypatch.setattr(signals, "gather_counts", feed)
        assert await signals.is_quarantined("org", "inst") is False

    def test_send_path_calls_the_gate(self):
        from pathlib import Path

        src = Path("aios/channels/evolution.py").read_text()
        assert "is_quarantined" in src
        assert "quarantined" in src
