from typing import Literal

from pydantic.json_schema import JsonSchemaValue
from pydantic_ai import InlineDefsJsonSchemaTransformer
from pydantic_ai.tools import GenerateToolJsonSchema
from pydantic_core import CoreSchema


class ToolInputShape(InlineDefsJsonSchemaTransformer):
    def transform(self, schema: JsonSchemaValue) -> JsonSchemaValue:
        return {
            key: value
            for key, value in schema.items()
            if key not in {"title", "default", "additionalProperties"}
        }


class TeachingToolSchema(GenerateToolJsonSchema):
    """Publish LearnHarness's inline input schema with Pydantic runtime validation."""

    def generate(
        self,
        schema: CoreSchema,
        mode: Literal["validation", "serialization"] = "validation",
    ) -> JsonSchemaValue:
        return ToolInputShape(super().generate(schema, mode=mode)).walk()
