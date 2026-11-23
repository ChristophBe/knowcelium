import { defineModule } from "@knowcel/module-sdk";
import { Connectors } from "./Connectors.tsx";
import manifest from "./manifest.ts";
import { ReplaceUpload } from "./ReplaceUpload.tsx";
import { Upload } from "./Upload.tsx";

export default defineModule({
  ...manifest,
  routes: [
    { index: true, element: <Upload /> },
    { path: "replace/:documentId", element: <ReplaceUpload /> },
    { path: "connectors", element: <Connectors /> },
  ],
});
