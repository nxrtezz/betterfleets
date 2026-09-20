import {
  ClerkProvider,
  Show,
  SignInButton,
  SignUpButton,
  UserButton,
} from "@clerk/react";

const publishableKey = process.env.VITE_CLERK_PUBLISHABLE_KEY;

function SignedOutControls() {
  return (
    <span className="clerk-auth-controls">
      <SignInButton mode="modal">
        <button type="button" className="button">
          Sign in
        </button>
      </SignInButton>
      <SignUpButton mode="modal">
        <button type="button" className="button">
          Sign up
        </button>
      </SignUpButton>
    </span>
  );
}

function AuthControls() {
  if (!publishableKey) {
    return (
      <a
        href={`/accounts/login/?next=${encodeURIComponent(window.location.pathname + window.location.search)}`}
        className="button"
      >
        Sign in
      </a>
    );
  }

  return (
    <ClerkProvider publishableKey={publishableKey}>
      <Show when="signed-out">
        <SignedOutControls />
      </Show>
      <Show when="signed-in">
        <UserButton />
      </Show>
    </ClerkProvider>
  );
}

export default AuthControls;
