"""Re-sync frontend from cagentos-frontend/ → static/, preserving our JS scripts.

Idempotent — safe to re-run. Re-copies HTML files (which contain new dark
mode CSS) and injects our <script> references before </body>.
"""
import shutil
from pathlib import Path

SRC = Path(r"d:\Projects\cagent-os\cagentos-frontend")
DST = Path(r"d:\Projects\cagent-os\src\cagent_os\interfaces\http\static")

# Our scripts that need to be re-injected after every HTML copy
# (because copy overwrites the previous version with our edits)
SCRIPT_INJECTIONS = {
    "chat.html": [
        '<script src="/static/assets/js/shell.js"></script>',
        '<script src="/static/assets/js/auth.js"></script>',
        '<script src="/static/assets/js/chat.js"></script>',
    ],
    "brief.html": [
        '<script src="/static/assets/js/shell.js"></script>',
        '<script src="/static/assets/js/auth.js"></script>',
    ],
    "knowledge.html": [
        '<script src="/static/assets/js/shell.js"></script>',
        '<script src="/static/assets/js/auth.js"></script>',
        '<script src="/static/assets/js/knowledge.js"></script>',
    ],
}


def inject_scripts(html_path: Path, scripts: list[str]) -> bool:
    """Insert <script> tags just before </body>. Returns True if changed."""
    content = html_path.read_text(encoding="utf-8")
    # Build the new script block
    new_block = "\n  ".join(scripts) + "\n"
    # Idempotency: check if already present
    marker = "<!-- app-injected-scripts -->"
    if marker in content:
        # Remove old injection block first
        start = content.find(marker)
        end = content.find("<!-- /app-injected-scripts -->", start)
        if end > 0:
            content = content[:start] + content[end + len("<!-- /app-injected-scripts -->"):]
    # Insert before </body>
    insertion = f"  {marker}\n  {new_block}  <!-- /app-injected-scripts -->\n"
    new_content = content.replace("</body>", insertion + "</body>", 1)
    if new_content != content:
        html_path.write_text(new_content, encoding="utf-8")
        return True
    return False


def main() -> None:
    # 1. Copy pages/ (overwrite — brings in new dark-mode CSS + toggle button)
    pages_dst = DST / "pages"
    pages_dst.mkdir(exist_ok=True)
    for html in ("chat.html", "brief.html", "knowledge.html"):
        src_file = SRC / "pages" / html
        if src_file.exists():
            shutil.copy2(src_file, pages_dst / html)
            size_kb = src_file.stat().st_size / 1024
            print(f"[OK] {html} copied ({size_kb:.1f} KB)")

    # 2. Re-inject our script references (wiped by the copy above)
    for html_name, scripts in SCRIPT_INJECTIONS.items():
        dst_file = pages_dst / html_name
        if dst_file.exists():
            changed = inject_scripts(dst_file, scripts)
            status = "re-injected" if changed else "unchanged"
            print(f"[OK] {html_name} scripts {status}: {len(scripts)} tags")

    # 3. Sync partials/ + assets/ (only if missing or older)
    partials_dst = DST / "partials"
    if (SRC / "partials").exists():
        if partials_dst.exists():
            shutil.rmtree(partials_dst)
        shutil.copytree(SRC / "partials", partials_dst)
        print("[OK] partials/ refreshed")

    assets_dst = DST / "assets"
    if not assets_dst.exists():
        shutil.copytree(SRC / "assets", assets_dst)
        count = sum(1 for _ in assets_dst.rglob("*") if _.is_file())
        print(f"[OK] assets/ copied ({count} files)")
    else:
        count = sum(1 for _ in assets_dst.rglob("*") if _.is_file())
        print(f"[SKIP] assets/ already exists ({count} files) — icon updates require manual delete")

    # 4. Sanity check: confirm dark mode made it through
    chat = (pages_dst / "chat.html").read_text(encoding="utf-8")
    has_dark = "html.dark" in chat and "toggleTheme" in chat
    has_scripts = "/static/assets/js/chat.js" in chat
    print()
    print(f"Sanity check (chat.html):")
    print(f"  dark-mode CSS + toggle button: {'✓' if has_dark else '✗ MISSING'}")
    print(f"  our chat.js reference:        {'✓' if has_scripts else '✗ MISSING'}")


if __name__ == "__main__":
    main()
