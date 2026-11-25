"""Sales pipeline slice (BusinessOS): followups + upload + sync shapes."""
import pytest

from aios.core.sales_pipeline import SalesPipeline


def test_followups_shape_and_idempotent_upload():
    p = SalesPipeline(store={"data": None})
    rows = p.followups(channels=["email"])
    assert rows and all(r["platform"] == "email" for r in rows)


@pytest.mark.asyncio
async def test_upload_idempotent():
    p = SalesPipeline(store={"data": None})
    r1 = await p.upload_sell_product("onwer", "Service")
    assert r1["ok"] is True and r1["duplicated"] is False
    r2 = await p.upload_sell_product("onwer", "Service")
    assert r2["ok"] is True and r2["duplicated"] is True


def test_pipeline_file_exists():
    from aios.core.sales_pipeline import business_os_baseline_path
    assert isinstance(business_os_baseline_path(), str)
