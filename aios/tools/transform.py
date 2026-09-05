import json
from pydantic import BaseModel, Field
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

class TransformInput(BaseModel):
    input: dict = Field(default_factory=dict)
    mapping: dict = Field(description="key -> template string com {{input.field}} ou valor estático")
    keep_unmapped: bool = Field(default=False)

class TransformTool(BaseTool):
    name = "transform"
    description = "Mapeia/renomeia campos: mapping {out_key: template}. Template suporta {{input.x}}"
    input_model = TransformInput

    async def run(self, input: dict | None = None, mapping: dict | None = None, keep_unmapped: bool = False) -> dict:
        input = input or {}
        mapping = mapping or {}
        from aios.core.expressions import render_mapping
        result = render_mapping(mapping, {"input": input, "json": input})
        if keep_unmapped:
            for k,v in input.items():
                if k not in result:
                    result[k]=v
        return {"ok": True, "output": result}

TOOL_REGISTRY["transform"] = {"code_reference": "aios.tools.transform.TransformTool"}
