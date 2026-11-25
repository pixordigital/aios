import yaml
from pathlib import Path

TPL = Path(__file__).parent.parent / "aios" / "templates" / "business_os"
EXPECTED_KPIS = {
    "sold_qty",
    "sold_value_brl",
    "new_clients",
    "happy_clients_pct",
    "tickets_closed",
    "sale_time_day",
}


def test_kpis_yaml_exists():
    assert (TPL / "KPI" / "kpis.yaml").exists()


def test_kpis_yaml_lists_expected_kpis():
    data = yaml.safe_load((TPL / "KPI" / "kpis.yaml").read_text())
    assert set(data["kpis"].keys()) == EXPECTED_KPIS


def test_checklist_md_exists():
    assert (TPL / "KPI" / "checklist.md").exists()


def test_checklist_md_mentions_all_kpis():
    text = (TPL / "KPI" / "checklist.md").read_text()
    for name in EXPECTED_KPIS:
        assert name in text
