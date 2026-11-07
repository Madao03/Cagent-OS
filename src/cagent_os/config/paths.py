from pathlib import Path


def resolve_project_root() -> Path:
    """Use the checkout in editable installs, or the working directory for a wheel."""
    package = Path(__file__).resolve().parents[1]
    checkout = package.parent.parent
    if package.parent.name == "src" and (checkout / "pyproject.toml").is_file():
        return checkout
    return Path.cwd()
