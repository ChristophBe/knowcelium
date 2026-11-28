import { buttonClass, Logo, Mark, ThemeToggle } from "@knowcel/ui";
import { useEffect, useState } from "react";
import { GithubMark } from "./GithubMark.tsx";
import { REPO } from "./links.ts";

export type PageId = "home" | "connectors";

/** The site's base path ("/knowcelium/" on GitHub Pages); pages live below it. */
export const BASE = import.meta.env.BASE_URL;
export const CONNECTORS_URL = `${BASE}connectors/`;

const SECTIONS = [
  { id: "features", label: "Features" },
  { id: "how-it-works", label: "How it works" },
  { id: "developers", label: "Developers" },
];

/** The sticky top bar: the logo, section links, GitHub and the theme switch. */
export function Nav({ page }: { page: PageId }) {
  // Sections belong to the home page; from another page they are links to it.
  const home = page === "home" ? "" : BASE;
  return (
    <div className="glass-subtle sticky top-0 z-20 border-b border-border px-4 sm:px-8">
      <nav aria-label="Main" className="mx-auto flex h-16 max-w-6xl items-center gap-4">
        <a
          href={page === "home" ? "#top" : BASE}
          aria-label="Knowcelium"
          className="flex items-center"
        >
          <Mark size={32} className="text-accent sm:hidden" />
          <Logo size={26} className="hidden font-serif sm:inline-flex" />
        </a>
        <ul className="ml-auto hidden items-center gap-1 md:flex">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`${home}#${s.id}`}
                className={buttonClass("ghost", "text-fg-muted hover:text-fg")}
              >
                {s.label}
              </a>
            </li>
          ))}
          <li>
            <a
              href={CONNECTORS_URL}
              aria-current={page === "connectors" ? "page" : undefined}
              className={buttonClass("ghost", "text-fg-muted hover:text-fg")}
            >
              Connectors
            </a>
          </li>
        </ul>
        <a
          href={REPO}
          className={buttonClass("ghost", "ml-auto md:ml-0")}
          aria-label="Knowcelium on GitHub"
        >
          <GithubMark className="size-4" />
        </a>
        <div className="w-24">
          <ClientOnlyThemeToggle />
        </div>
      </nav>
    </div>
  );
}

/**
 * The theme switch reads the saved choice from localStorage, which the
 * prerendered HTML can't know; rendering it after hydration avoids a mismatch.
 * The pre-paint script in index.html has already applied the theme itself.
 */
function ClientOnlyThemeToggle() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted ? <ThemeToggle /> : <div className="h-8 rounded-full bg-surface-muted" />;
}
