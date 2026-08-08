/**
 * CagentOS navigation config — shared between vanilla shell.js and React sidebar.
 * Single source of truth for nav items. Add new pages here only.
 */
window.CAGENT_NAV_ITEMS = [
  { id: "chat",      label: "对话面板",   href: "/",             icon: "chat",        disabled: false },
  { id: "brief",     label: "每日简报",   href: "/brief",        icon: "calendar",    disabled: true },
  { id: "dashboard", label: "定制化看板", href: null,            icon: "monitor",     disabled: true },
  { id: "opinions",  label: "观点库",     href: "/app/opinions", icon: "brain",       disabled: false },
  { id: "knowledge", label: "共享知识库", href: "/knowledge",    icon: "doc",         disabled: false },
  { id: "roadmap",   label: "开发路线图", href: "/roadmap",      icon: "design-flow", disabled: false },
  { id: "feedback",  label: "反馈中心",   href: "/feedback",     icon: "ai_bulb",     disabled: false },
  { id: "about",     label: "关于",       href: "/about",        icon: "info",        disabled: false },
];
