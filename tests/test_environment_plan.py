import json

from forge.environment import environment_plan
from forge.integrations import parse_example


def test_environment_plan_discovers_node_browser_build_and_python_without_execution():
    plan = environment_plan(
        {
            "package.json": json.dumps(
                {
                    "packageManager": "pnpm@10.0.0",
                    "scripts": {"build": "arbitrary project build"},
                    "devDependencies": {"@playwright/test": "1.62.1"},
                }
            ),
            "pnpm-lock.yaml": "",
            "pyproject.toml": "",
            "src/app.py": "raise RuntimeError('never executed')",
        }
    )
    assert plan["runtimes"] == ["python", "node"]
    assert plan["build"] and plan["browser_tests"] and plan["package_manager"] == "pnpm"


def test_named_provider_variable_disambiguates_an_opaque_key_without_llm():
    result = parse_example(code='export DEEPSEEK_API_KEY="opaque-provider-fixture"')
    assert result["endpoint"] == "https://api.deepseek.com"
    assert result["key"] == "opaque-provider-fixture"
