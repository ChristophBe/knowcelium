import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { ConnectorsPage } from "./ConnectorsPage.tsx";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root missing");
// Each page's HTML names itself on the script tag, so the right one hydrates.
const connectors =
  document.querySelector("script[data-page]")?.getAttribute("data-page") === "connectors";
const app = <StrictMode>{connectors ? <ConnectorsPage /> : <App />}</StrictMode>;
// The build prerenders the page into #root (prerender.ts); the dev server serves it empty.
if (root.firstElementChild) hydrateRoot(root, app);
else createRoot(root).render(app);
