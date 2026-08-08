import { useState, useEffect } from "react";
import Opinions from "./pages/Opinions";

/** Simple page registry — add new React pages here. */
const PAGES: Record<string, { title: string; render: () => JSX.Element }> = {
  opinions: {
    title: "观点库",
    render: () => <Opinions />,
  },
};

function App() {
  const [path, setPath] = useState(window.location.pathname.replace(/^\/app\/?/, "").replace(/^\/+/, ""));
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("cagentos-sidebar-collapsed") === "1"; } catch { return false; }
  });

  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem("cagentos-sidebar-collapsed", next ? "1" : "0"); } catch {}
  };

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname.replace(/^\/app\/?/, "").replace(/^\/+/, ""));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const pageKey = Object.keys(PAGES).find((k) => path.startsWith(k));
  const page = pageKey ? PAGES[pageKey] : null;

  // Shared nav config from nav-config.js (loaded in main.tsx)
  const navItems: any[] = (window as any).CAGENT_NAV_ITEMS || [];

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <aside className={`app-sidebar${collapsed ? " collapsed" : ""}`}>
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
          <button
            className="sidebar-collapse-btn"
            aria-label="收起侧边栏"
            title="收起侧边栏"
            onClick={() => toggleCollapsed()}
          >
            <span data-icon="arrow-collapse" className="sidebar-collapse-icon" />
          </button>
        </div>
        <nav className="app-sidebar-nav">
          {navItems.map((item) => (
            <a
              key={item.id}
              className={`sidebar-nav-item${pageKey === item.id ? " active" : ""}${
                item.disabled ? " disabled" : ""
              }`}
              href={item.href || "#"}
              title={item.label}
              onClick={(e) => {
                if (item.disabled) {
                  e.preventDefault();
                }
              }}
            >
              <span data-icon={item.icon} className="sidebar-nav-icon" />
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
