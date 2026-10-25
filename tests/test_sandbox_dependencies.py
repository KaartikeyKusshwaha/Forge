import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "sandbox_dependencies", Path(__file__).resolve().parents[1] / "scripts/sandbox_dependencies.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_static_project_and_nested_test_requirements():
    requirements, install = module.python_requirements(
        {
            "pyproject.toml": '[project]\nname="example"\ndependencies=["httpx>=0.27"]\n'
            '[project.optional-dependencies]\ntest=["pytest-asyncio"]\n'
            '[build-system]\nrequires=["setuptools>=77", "wheel"]\n',
            "requirements-dev.txt": "-r tests/requirements.txt\n",
            "tests/requirements.txt": "anyio>=4 # tests\n",
        }
    )
    assert install
    assert {"httpx>=0.27", "pytest-asyncio", "anyio>=4", "setuptools>=77"} <= set(requirements)


@pytest.mark.parametrize(
    "declaration",
    ["evil @ https://example.com/evil.tar.gz", "--index-url https://example.com", "-r ../secret", "./local"],
)
def test_unsafe_dependency_sources_are_rejected(declaration):
    with pytest.raises(ValueError):
        module.python_requirements({"requirements.txt": declaration})


def test_dynamic_dependencies_fail_before_executing_build_code():
    with pytest.raises(ValueError, match="Dynamic"):
        module.python_requirements({"pyproject.toml": '[project]\nname="x"\ndynamic=["dependencies"]'})
