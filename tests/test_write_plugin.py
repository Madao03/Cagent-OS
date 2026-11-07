from cagent_os.config import Settings
from cagent_os.plugins.contracts import ToolRequest
from cagent_os.plugins.write.plugin import WritePlugin


def test_write_stays_within_knowledge_directory(tmp_path, monkeypatch):
    plugin = WritePlugin(Settings())
    monkeypatch.setattr(plugin, "_cwd", tmp_path)
    write = plugin.handler("write.file")

    def request(path, mode="overwrite"):
        return write(ToolRequest("write.file", {"path": path, "content": "abc", "mode": mode}))

    assert request("knowledge/notes/test.md").status == "ok"
    assert request("knowledge/notes/test.md", "append").status == "ok"
    assert (tmp_path / "knowledge/notes/test.md").read_text() == "abcabc"
    for path in ("knowledge-copy/test.md", "knowledge/../knowledge-copy/test.md"):
        assert request(path).error_code == "path_not_allowed"
    assert not (tmp_path / "knowledge-copy").exists()
