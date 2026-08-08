import { useLocation } from "react-router-dom";

/** Simple page registry — add new React pages here. */
const PAGES: Record<string, { title: string; render: () => JSX.Element }> = {
  opinions: {
    title: "观点库",
    render: () => (
      <div className="react-page">
        <h1>观点库</h1>
        <p className="subtitle">在这里查看和管理你保存的观点。</p>
        <div className="placeholder-card">
          <p>观点库功能开发中…</p>
          <p className="hint">React 基建已就绪，即将接入后端 API。</p>
        </div>
      </div>
    ),
  },
};

function App() {
  const location = useLocation();

  // Extract page key from pathname: /app/opinions → "opinions"
  const path = location.pathname.replace(/^\/app\/?/, "").replace(/^\/+/, "");
  const pageKey = Object.keys(PAGES).find((k) => path.startsWith(k));

  const page = pageKey ? PAGES[pageKey] : null;

  // Sidebar nav (shared with vanilla pages via shell.js)
  const navItems = [
    { key: "chat", label: "对话面板", disabled: false, href: "/" },
    { key: "brief", label: "每日简报", disabled: true },
    { key: "dashboard", label: "定制化看板", disabled: true },
    { key: "opinions", label: "观点库", disabled: false, href: "/app/opinions" },
    { key: "knowledge", label: "共享知识库", disabled: false, href: "/knowledge" },
    { key: "roadmap", label: "开发路线图", disabled: false, href: "/roadmap" },
    { key: "feedback", label: "反馈中心", disabled: false, href: "/feedback" },
    { key: "about", label: "关于", disabled: false, href: "/about" },
  ];

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-sidebar-logo">
          <span
            className="sidebar-logo-icon"
            dangerouslySetInnerHTML={{
              __html:
                '<span style="display:inline-block;width:28px;height:28px;border-radius:6px;background:linear-gradient(135deg,#4B3FE3,#6A6FFF);text-align:center;line-height:28px;color:#fff;font-weight:700;font-size:14px;font-family:var(--font-family-mono,monospace)">C</span>',
            }}
          />
          <span className="app-sidebar-logo-text">
            <span className="logo-title">CagentOS</span>
            <span className="logo-subtitle">投研工作台</span>
          </span>
        </div>
        <nav className="app-sidebar-nav">
          {navItems.map((item) => (
            <a
              key={item.key}
              className={`sidebar-nav-item${pageKey === item.key ? " active" : ""}${
                item.disabled ? " disabled" : ""
              }`}
              href={item.href || "#"}
              onClick={(e) => {
                if (item.disabled) {
                  e.preventDefault();
                }
              }}
            >
              <span className="sidebar-nav-label">
                {item.label}
                {item.disabled && <sup className="sidebar-nav-tag">建设中</sup>}
              </span>
            </a>
          ))}
        </nav>
        <div className="app-sidebar-footer">
          <div className="sidebar-version">Beta · 2026</div>
        </div>
      </aside>

      <div className="app-main">
        <div className="content">
          {page ? (
            page.render()
          ) : (
            <div className="react-page">
              <h1>404</h1>
              <p>页面不存在。</p>
              <a href="/">返回对话</a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
