import type { ReactNode } from "react";
import { Footer } from "./Footer.tsx";
import { Nav, type PageId } from "./Nav.tsx";

/** What every page shares: skip link, top bar, the main landmark and the footer. */
export function Page({ page, children }: { page: PageId; children: ReactNode }) {
  return (
    <div id="top">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-30 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <Nav page={page} />
      <main id="main">{children}</main>
      <Footer />
    </div>
  );
}
