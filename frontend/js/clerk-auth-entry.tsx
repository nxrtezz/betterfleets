import React from "react";
import { createRoot } from "react-dom/client";

import AuthControls, { ClerkSignIn } from "./ClerkAuth";

const rootElement = document.getElementById("clerk-auth-root");
const signInElement = document.getElementById("clerk-sign-in-root");

if (rootElement) {
  createRoot(rootElement).render(
    <React.StrictMode>
      <AuthControls />
    </React.StrictMode>,
  );
}

if (signInElement) {
  createRoot(signInElement).render(
    <React.StrictMode>
      <ClerkSignIn />
    </React.StrictMode>,
  );
  if (process.env.VITE_CLERK_PUBLISHABLE_KEY) {
    document.querySelector(".legacy-auth-form")?.remove();
  }
}
