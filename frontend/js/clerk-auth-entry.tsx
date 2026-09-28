import React from "react";
import { createRoot } from "react-dom/client";

// Use dynamic import to handle React 19 compatibility issues with Clerk
async function loadClerkAuth() {
  try {
    const clerkModule = await import("./ClerkAuth");
    return {
      AuthControls: clerkModule.default,
      ClerkAccount: clerkModule.ClerkAccount,
      ClerkSignIn: clerkModule.ClerkSignIn,
      ClerkSignOut: clerkModule.ClerkSignOut,
      ClerkSignUp: clerkModule.ClerkSignUp,
    };
  } catch (error) {
    console.warn("Clerk authentication disabled due to compatibility error:", error);
    return null;
  }
}

const rootElement = document.getElementById("clerk-auth-root");
const signInElement = document.getElementById("clerk-sign-in-root");
const signUpElement = document.getElementById("clerk-sign-up-root");
const accountElement = document.getElementById("clerk-account-root");
const signOutElement = document.getElementById("clerk-sign-out-root");

const redirectElement = document.querySelector("[data-clerk-redirect-url]");
if (redirectElement instanceof HTMLElement) {
  document.body.dataset.clerkRedirectUrl =
    redirectElement.dataset.clerkRedirectUrl || "/";
}

// Load Clerk auth and render components
loadClerkAuth().then((clerkAuth) => {
  if (!clerkAuth) return;

  const { AuthControls, ClerkAccount, ClerkSignIn, ClerkSignOut, ClerkSignUp } = clerkAuth;

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

  if (signUpElement) {
    createRoot(signUpElement).render(
      <React.StrictMode>
        <ClerkSignUp />
      </React.StrictMode>,
    );
  }

  if (accountElement) {
    createRoot(accountElement).render(
      <React.StrictMode>
        <ClerkAccount />
      </React.StrictMode>,
    );
  }

  if (signOutElement) {
    createRoot(signOutElement).render(
      <React.StrictMode>
        <ClerkSignOut />
      </React.StrictMode>,
    );
  }
}).catch((error) => {
  console.error("Failed to load Clerk authentication:", error);
});
