// Renders each page to static HTML after `vite build`, so it reads without JavaScript
// and search engines see the content; the client bundle then hydrates it.
import { readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("dist/", import.meta.url));
const ssr = fileURLToPath(new URL("dist-ssr/", import.meta.url));

const { render } = (await import(`${ssr}entry-server.js`)) as {
  render: (page: "home" | "connectors") => string;
};
const pages = [
  { name: "home", file: "index.html" },
  { name: "connectors", file: "connectors/index.html" },
] as const;
for (const { name, file } of pages) {
  const template = await readFile(`${dist}${file}`, "utf8");
  if (!template.includes("<!--app-->")) throw new Error(`${file} has no <!--app--> placeholder`);
  await writeFile(`${dist}${file}`, template.replace("<!--app-->", render(name)));
}
await rm(ssr, { recursive: true });
