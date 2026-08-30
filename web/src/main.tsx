import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { Providers } from "./app/providers";
import { router } from "./app/router";
import i18n, { i18nReady } from "./i18n";
import "./index.css";

const root = createRoot(document.getElementById("root")!);

function renderApp(): void {
  root.render(
    <StrictMode>
      <Providers>
        <RouterProvider router={router} />
      </Providers>
    </StrictMode>,
  );
}

void i18nReady.then(() => {
  renderApp();
  i18n.on("languageChanged", renderApp);
});
