import { defineManifest } from "@knowcel/module-sdk";
import { Plug, Upload } from "@knowcel/ui";

export default defineManifest({
  id: "ingestion",
  title: "Upload",
  icon: Upload,
  nav: [
    { path: "", label: "Upload", icon: Upload, order: 30 },
    { path: "connectors", label: "Connectors", icon: Plug, requiresPlatformAdmin: true, order: 55 },
  ],
});
