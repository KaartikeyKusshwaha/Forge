"""Shared typed contracts for engineering roles and provider output controls."""

from pydantic import BaseModel, Field


class Edit(BaseModel):
    path: str = Field(max_length=250)
    content: str | None = Field(max_length=500_000)


class Changes(BaseModel):
    summary: str = Field(max_length=4000)
    edits: list[Edit] = Field(min_length=1, max_length=10)


class Plan(BaseModel):
    summary: str = Field(max_length=4000)
    steps: list[str] = Field(min_length=1, max_length=12)
    acceptance: list[str] = Field(min_length=1, max_length=12)
    files: list[str] = Field(max_length=20)
    needs_input: bool = False
    question: str = Field(default="", max_length=2000)


class Review(BaseModel):
    summary: str = Field(max_length=4000)
    findings: list[str] = Field(max_length=20)
    acceptable: bool


class TestChanges(BaseModel):
    edits: list[Edit] = Field(max_length=10)


ROLE_CONTRACTS = {"planner": Plan, "coder": Changes, "tester": TestChanges, "reviewer": Review}


def output_schema(role, context):
    schema = ROLE_CONTRACTS[role].model_json_schema()
    paths = context.get("available_paths")
    if role == "planner" and isinstance(paths, list) and 0 < len(paths) <= 200:
        schema["properties"]["files"]["items"] = {"type": "string", "enum": paths}
    return schema
