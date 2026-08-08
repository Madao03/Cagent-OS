import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

// Load global CSS (single source of truth — same files used by vanilla pages)
const cssFiles = [
  "/static/css/tokens.css?v=1",
  "/static/css/sidebar.css?v=1",
  "/static/assets/css/icons.css",
];
cssFiles.forEach((href) => {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
});

// Load shared nav config
const navScript = document.createElement("script");
navScript.src = "/static/js/nav-config.js";
document.head.appendChild(navScript);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
