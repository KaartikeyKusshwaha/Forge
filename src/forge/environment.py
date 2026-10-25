"""Static sandbox preparation plan; never executes repository configuration locally."""

import json


def environment_plan(files):
    manifests = [
        p
        for p in files
        if p
        in {
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "uv.lock",
            "poetry.lock",
        }
    ]
    node = json.loads(files.get("package.json", "{}"))
    manager = node.get("packageManager", "npm").split("@")[0]
    if "pnpm-lock.yaml" in files:
        manager = "pnpm"
    elif "yarn.lock" in files:
        manager = "yarn"
    dependencies = {**node.get("dependencies", {}), **node.get("devDependencies", {})}
    runtimes = []
    if any(p.endswith(".py") for p in files):
        runtimes.append("python")
    if "package.json" in files or any(p.endswith((".test.ts", ".test.js")) for p in files):
        runtimes.append("node")
    return {
        "runtimes": runtimes,
        "manifests": sorted(manifests),
        "package_manager": manager,
        "build": "build" in node.get("scripts", {}),
        "browser_tests": bool({"@playwright/test", "playwright"} & dependencies.keys()),
        "network": "Package retrieval only; project builds and tests use a private network namespace",
        "execution": "Disposable GitHub VM, non-root, no host execution",
        "environment": {"CI": "1", "NODE_ENV": "test", "PYTHONDONTWRITEBYTECODE": "1"},
        "unavailable": [
            name
            for path, name in [
                ("Cargo.toml", "Rust profile"),
                ("go.mod", "Go profile"),
                ("Gemfile", "Ruby profile"),
                ("composer.json", "PHP profile"),
            ]
            if path in files
        ],
    }
