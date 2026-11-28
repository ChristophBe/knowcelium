import { StrictMode } from "react";
import { renderToString } from "react-dom/server";
import { App } from "./App.tsx";
import { ConnectorsPage } from "./ConnectorsPage.tsx";

export type PageName = "home" | "connectors";

/** A page as static HTML, for prerender.ts. */
export function render(page: PageName = "home") {
  return renderToString(
    <StrictMode>{page === "connectors" ? <ConnectorsPage /> : <App />}</StrictMode>,
  );
}
