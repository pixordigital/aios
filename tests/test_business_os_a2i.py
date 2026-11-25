import json
from pathlib import Path

TPL = Path(__file__).parent.parent / "aios" / "templates" / "business_os"


def test_money_md_exists():
    assert (TPL / "Money" / "money.md").exists()


def test_mcp_json_valid_jsonl():
    for mcp in TPL.rglob("mcp.json"):
        for line in mcp.read_text().splitlines():
            if line.strip():
                json.loads(line)
