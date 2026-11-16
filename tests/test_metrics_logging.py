"""Phase 5: metric snapshots go to the aios.metrics logger, not local files."""

import json
import logging

from aios.config import settings
from aios.core import tracing


def test_metric_snapshot_logged_not_written(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    caplog.set_level(logging.INFO, logger="aios.metrics")

    tracing.flush_metrics()

    records = [r for r in caplog.records if r.name == "aios.metrics"]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert set(payload) == set(tracing.METRICS) | {"_ts"}
    assert isinstance(payload["_ts"], int)
    assert not (tmp_path / "metrics").exists()
