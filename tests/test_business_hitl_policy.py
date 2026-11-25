import pytest

from aios.core.business_hitl_policy import (
    HITL_REQUIRED_CATEGORIES,
    SideEffectCategory,
    owner_accountability_notice,
    requires_human_approval,
)


@pytest.mark.parametrize(
    "category",
    [
        SideEffectCategory.MONEY,
        SideEffectCategory.EXTERNAL_COMMITMENT,
        SideEffectCategory.LEGAL,
        SideEffectCategory.DATA_DELETE,
        SideEffectCategory.BULK_SEND,
    ],
)
def test_high_risk_side_effect_categories_require_hitl(category):
    assert requires_human_approval(category) is True
    assert requires_human_approval(category.value) is True
    assert category in HITL_REQUIRED_CATEGORIES


def test_read_only_does_not_require_hitl():
    assert requires_human_approval(SideEffectCategory.READ_ONLY) is False
    assert requires_human_approval("read_only") is False


def test_owner_accountability_notice_mentions_human_owner_accountable():
    notice = owner_accountability_notice()
    notice_lower = notice.lower()
    assert "human owner" in notice_lower
    assert "accountable" in notice_lower
