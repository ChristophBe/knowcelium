import { Mark } from "@knowcel/ui";
import { REPO, repoPath } from "./links.ts";

const FOOTER_LINKS = [
  { href: REPO, label: "GitHub" },
  { href: repoPath("docs/user-manual/README.md"), label: "User manual" },
  { href: repoPath("docs/architecture/overview.md"), label: "Architecture" },
  { href: repoPath("CONTRIBUTING.md"), label: "Contributing" },
];

export function Footer() {
  return (
    <footer className="border-t border-border px-4 py-10 sm:px-8">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 text-sm text-fg-muted">
        <p className="flex items-center gap-2">
          <Mark size={20} className="text-accent" />
          <span className="font-medium text-fg">Knowcelium</span> · the knowledge backbone of your
          organization
        </p>
        <ul className="flex flex-wrap gap-x-5 gap-y-2">
          {FOOTER_LINKS.map((l) => (
            <li key={l.label}>
              <a href={l.href} className="hover:text-fg hover:underline">
                {l.label}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </footer>
  );
}
