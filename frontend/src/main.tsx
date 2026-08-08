import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/tokens.css";

// Load vanilla icon system (data-icon + CSS mask) for visual consistency
const iconLink = document.createElement("link");
iconLink.rel = "stylesheet";
iconLink.href = "/static/assets/css/icons.css";
document.head.appendChild(iconLink);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
