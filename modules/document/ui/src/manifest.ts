import { defineManifest, lazySearch } from "@knowcel/module-sdk";
import { FileText } from "@knowcel/ui";
import { notifications } from "./notifications.ts";

export default defineManifest({
  id: "document",
  title: "Documents",
  order: 20,
  icon: FileText,
  notifications: notifications.categories,
  search: lazySearch("Documents", () =>
    import("./searchProvider.ts").then((m) => m.documentSearch),
  ),
});
