import { useState, useEffect, useCallback } from "react";
import { opinionsApi, type Opinion } from "../lib/api";

const CATEGORIES = [
  { key: "", label: "全部" },
  { key: "fact", label: "📊 事实" },
  { key: "opinion", label: "💭 观点" },
  { key: "framework", label: "🔧 框架" },
];

const CATEGORY_COLORS: Record<string, string> = {
  fact: "#2F74FF",
  opinion: "#4B3FE3",
  framework: "#15A877",
};

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" }) +
      " " + d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export default function Opinions() {
  const [opinions, setOpinions] = useState<Opinion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editNote, setEditNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await opinionsApi.list(filter || undefined);
      setOpinions(data.items || []);
    } catch (e: any) {
      setError(e.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const filtered = search
    ? opinions.filter((o) =>
        o.selected_text.toLowerCase().includes(search.toLowerCase()) ||
        (o.note || "").toLowerCase().includes(search.toLowerCase())
      )
    : opinions;

  async function handleDelete(id: string) {
    if (!confirm("确定删除这条观点？")) return;
    try {
      await opinionsApi.delete(id);
      setOpinions(opinions.filter((o) => o.id !== id));
    } catch (e: any) {
      alert("删除失败: " + e.message);
    }
  }

  async function handleSaveEdit(id: string) {
    try {
      await opinionsApi.update(id, { note: editNote });
      setOpinions(opinions.map((o) => o.id === id ? { ...o, note: editNote } : o));
      setEditingId(null);
    } catch (e: any) {
      alert("保存失败: " + e.message);
    }
  }

  async function handleCategoryChange(id: string, category: string) {
    try {
      await opinionsApi.update(id, { category });
      setOpinions(opinions.map((o) => o.id === id ? { ...o, category } : o));
    } catch (e: any) {
      alert("修改失败: " + e.message);
    }
  }

  return (
    <div className="react-page">
      <h1>观点库</h1>
      <p className="subtitle">在这里查看和管理你保存的观点。</p>

      {/* Search */}
      <input
        type="text"
        className="opinion-search"
        placeholder="搜索观点…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{
          width: "100%", padding: "8px 12px", marginBottom: "16px",
          border: "1px solid var(--border-neutral-l2)", borderRadius: "6px",
          fontSize: "13px", background: "var(--bg-base-default)", color: "var(--text-default)",
          boxSizing: "border-box",
        }}
      />

      {/* Category filter */}
      <div style={{ display: "flex", gap: "8px", marginBottom: "24px" }}>
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            onClick={() => setFilter(cat.key)}
            style={{
              padding: "4px 12px", borderRadius: "4px", cursor: "pointer",
              border: filter === cat.key ? "1px solid var(--bg-brand)" : "1px solid var(--border-neutral-l2)",
              background: filter === cat.key ? "var(--bg-brand-surface-l1)" : "transparent",
              color: filter === cat.key ? "var(--bg-brand)" : "var(--text-secondary)",
              fontSize: "12px", fontWeight: 500,
            }}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div style={{ color: "var(--status-error-default)", marginBottom: "16px", fontSize: "13px" }}>
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ color: "var(--text-tertiary)", textAlign: "center", padding: "48px" }}>
          加载中…
        </div>
      )}

      {/* Empty */}
      {!loading && filtered.length === 0 && (
        <div className="placeholder-card">
          <p>{search ? "没有匹配的观点" : "还没有保存任何观点"}</p>
          <p className="hint">在对话中选中文字 → 📌 存入观点库</p>
        </div>
      )}

      {/* List */}
      {!loading && filtered.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {filtered.map((op) => (
            <div
              key={op.id}
              style={{
                borderLeft: `3px solid ${CATEGORY_COLORS[op.category] || "var(--border-neutral-l3)"}`,
                background: "var(--bg-overlay-l1)",
                borderRadius: "0 8px 8px 0",
                padding: "12px 16px",
              }}
            >
              {/* Category selector */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <select
                  value={op.category}
                  onChange={(e) => handleCategoryChange(op.id, e.target.value)}
                  style={{
                    fontSize: "11px", padding: "2px 8px", borderRadius: "4px",
                    border: "1px solid var(--border-neutral-l2)",
                    background: "var(--bg-base-default)", color: "var(--text-secondary)",
                  }}
                >
                  <option value="fact">📊 事实</option>
                  <option value="opinion">💭 观点</option>
                  <option value="framework">🔧 框架</option>
                </select>
                <span style={{ fontSize: "11px", color: "var(--text-tertiary)" }}>
                  {formatDate(op.created_at)}
                </span>
              </div>

              {/* Text */}
              <div style={{
                fontSize: "14px", lineHeight: 1.6, color: "var(--text-default)",
                whiteSpace: "pre-wrap", wordBreak: "break-word", marginBottom: "8px",
              }}>
                {op.selected_text}
              </div>

              {/* Note (display/edit) */}
              {editingId === op.id ? (
                <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
                  <input
                    type="text"
                    value={editNote}
                    onChange={(e) => setEditNote(e.target.value)}
                    style={{
                      flex: 1, padding: "4px 8px", fontSize: "12px",
                      border: "1px solid var(--bg-brand)", borderRadius: "4px",
                      background: "var(--bg-base-default)", color: "var(--text-default)",
                    }}
                    autoFocus
                  />
                  <button onClick={() => handleSaveEdit(op.id)} style={{ padding: "4px 12px", fontSize: "12px", cursor: "pointer", border: "none", borderRadius: "4px", background: "var(--bg-brand)", color: "#fff" }}>保存</button>
                  <button onClick={() => setEditingId(null)} style={{ padding: "4px 12px", fontSize: "12px", cursor: "pointer", border: "1px solid var(--border-neutral-l2)", borderRadius: "4px", background: "transparent", color: "var(--text-secondary)" }}>取消</button>
                </div>
              ) : (
                op.note && (
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "8px", fontStyle: "italic" }}>
                    📝 {op.note}
                  </div>
                )
              )}

              {/* Actions */}
              <div style={{ display: "flex", gap: "12px" }}>
                <button
                  onClick={() => { setEditingId(op.id); setEditNote(op.note || ""); }}
                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: "11px", color: "var(--text-tertiary)", padding: 0 }}
                >
                  编辑备注
                </button>
                <button
                  onClick={() => handleDelete(op.id)}
                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: "11px", color: "var(--status-error-default)", padding: 0 }}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
