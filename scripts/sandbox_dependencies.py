"""Static dependency planning. Never imports or executes a target project's code."""
import re
import tomllib
from pathlib import PurePosixPath

try:
    from packaging.requirements import Requirement
except ImportError:
    from pip._vendor.packaging.requirements import Requirement


def python_requirements(files):
    requirements = ["pytest==8.3.5"]
    install_project = False
    if "pyproject.toml" in files:
        data = tomllib.loads(files["pyproject.toml"])
        project = data.get("project", {})
        requirements.extend(project.get("dependencies", []))
        for name, values in project.get("optional-dependencies", {}).items():
            if name.lower() in {"test", "tests", "testing", "dev"}:
                requirements.extend(values)
        requirements.extend(data.get("dependency-groups", {}).get("dev", []))
        requirements.extend(data.get("dependency-groups", {}).get("test", []))
        requirements.extend(data.get("build-system", {}).get("requires", ["setuptools", "wheel"]))
        install_project = bool(project.get("name") or data.get("build-system"))
        if project.get("dynamic") and "dependencies" in project["dynamic"]:
            raise ValueError("Dynamic dependencies need a static requirements.txt declaration.")
    elif "setup.py" in files or "setup.cfg" in files:
        requirements.extend(["setuptools", "wheel"])
        install_project = True
    visited = set()

    def read_requirements(path):
        if path in visited:
            return
        visited.add(path)
        if path not in files:
            raise ValueError(f"Missing dependency manifest: {path}")
        for line in files[path].splitlines():
            line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                child = str(PurePosixPath(path).parent / line[3:].strip())
                if ".." in PurePosixPath(child).parts or child.startswith("/"):
                    raise ValueError("Requirements include escapes the source tree.")
                read_requirements(child)
            else:
                requirements.append(line)

    for path in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt"):
        if path in files:
            read_requirements(path)
    validated = []
    for value in requirements:
        if not isinstance(value, str) or len(value) > 1000 or any(c in value for c in "\r\n\x00"):
            raise ValueError("Unsupported dependency declaration.")
        requirement = Requirement(value)
        if requirement.url:
            raise ValueError("Direct URL, VCS and local dependencies require a reviewed setup profile.")
        validated.append(str(requirement))
    if len(validated) > 300:
        raise ValueError("Dependency inventory exceeds 300 declarations.")
    return sorted(set(validated)), install_project
