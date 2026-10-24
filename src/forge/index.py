import ast
import re


def retrieve(files: dict[str, str], issue: str, limit: int = 10) -> list[dict]:
    """Bounded lexical/symbol retrieval with line-addressable evidence."""
    terms = {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", issue)}
    terms -= {"the", "and", "with", "this", "that", "from", "should", "currently"}
    found = []
    for path, text in files.items():
        symbols = []
        if path.endswith(".py"):
            try:
                tree = ast.parse(text)
                symbols = [
                    n.name
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                ]
            except SyntaxError:
                pass
        elif path.endswith((".ts", ".tsx", ".js", ".jsx")):
            symbols = re.findall(r"(?:function|class|const|interface|type)\s+([A-Za-z_$][\w$]*)", text)
        score = sum(
            6 * (t in path.lower()) + 10 * (t in " ".join(symbols).lower()) + min(text.lower().count(t), 8)
            for t in terms
        )
        if path.lower().endswith((".md", ".json", ".toml")):
            score *= 0.6
        if score:
            numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(text.splitlines(), 1))
            found.append(
                dict(
                    path=path,
                    symbols=symbols[:40],
                    score=score,
                    start_line=1,
                    end_line=min(len(text.splitlines()), 300),
                    content=numbered[:18_000],
                )
            )
    return sorted(found, key=lambda r: (-r["score"], r["path"]))[:limit]
