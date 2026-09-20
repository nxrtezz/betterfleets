import React from "react";
import { createRoot } from "react-dom/client";

import AuthControls from "./ClerkAuth";

const rootElement = document.getElementById("clerk-auth-root");

if (rootElement) {
  createRoot(rootElement).render(
    <React.StrictMode>
      <AuthControls />
    </React.StrictMode>,
  );
}
