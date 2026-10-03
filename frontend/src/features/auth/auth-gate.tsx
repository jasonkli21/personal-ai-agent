"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import {
  clearGoogleIdToken,
  configureAuth,
  getAuthTokenServerSnapshot,
  getAuthTokenSnapshot,
  isGoogleOidcEnabled,
  setGoogleIdToken,
  subscribeAuth,
} from "../../lib/auth";

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (options: {
            client_id: string;
            callback: (response: { credential?: string }) => void;
            auto_select: boolean;
            cancel_on_tap_outside: boolean;
          }) => void;
          renderButton: (element: HTMLElement, options: Record<string, string | boolean>) => void;
          disableAutoSelect: () => void;
        };
      };
    };
  }
}

export function AuthGate({
  children,
  nonce,
  authMode,
  clientId,
}: {
  children: ReactNode;
  nonce?: string | null;
  authMode: string;
  clientId: string;
}) {
  configureAuth(authMode);
  const token = useSyncExternalStore(
    subscribeAuth,
    getAuthTokenSnapshot,
    getAuthTokenServerSnapshot,
  );
  const buttonRef = useRef<HTMLDivElement>(null);
  const initializedClient = useRef<string | null>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const [signInError, setSignInError] = useState<string | null>(null);
  const enabled = isGoogleOidcEnabled();

  const initializeGoogleSignIn = useCallback(() => {
    const googleId = window.google?.accounts?.id;
    if (!googleId || !buttonRef.current || !clientId || initializedClient.current === clientId) return;
    initializedClient.current = clientId;
    googleId.initialize({
      client_id: clientId,
      auto_select: false,
      cancel_on_tap_outside: false,
      callback: ({ credential }) => {
        if (!credential || !setGoogleIdToken(credential)) {
          setSignInError("Google sign-in returned an invalid or expired credential. Try again.");
          return;
        }
        setSignInError(null);
      },
    });
    googleId.renderButton(buttonRef.current, {
      type: "standard",
      theme: "outline",
      size: "large",
      shape: "rectangular",
      text: "signin_with",
    });
  }, [clientId]);

  useEffect(() => {
    if (scriptLoaded) initializeGoogleSignIn();
  }, [initializeGoogleSignIn, scriptLoaded]);

  if (!enabled) return children;
  if (token) {
    return (
      <>
        <div style={{ display: "flex", justifyContent: "flex-end", padding: ".5rem 1rem" }}>
          <button type="button" onClick={() => {
            window.google?.accounts?.id?.disableAutoSelect();
            clearGoogleIdToken();
          }}>Sign out</button>
        </div>
        {children}
      </>
    );
  }

  return (
    <main style={{ maxWidth: "32rem", margin: "12vh auto", padding: "1.5rem" }}>
      <h1>Sign in to Personal AI</h1>
      <p>Only the configured personal account can access conversations and research.</p>
      {!clientId ? (
        <p role="alert">Google sign-in is not configured for this deployment.</p>
      ) : (
        <>
          <div ref={buttonRef} aria-label="Sign in with Google" />
          <Script
            src="https://accounts.google.com/gsi/client"
            strategy="afterInteractive"
            nonce={nonce ?? undefined}
            referrerPolicy="origin"
            onLoad={() => setScriptLoaded(true)}
            onError={() => setSignInError("Google sign-in could not be loaded. Check your connection and try again.")}
          />
        </>
      )}
      {signInError && <p role="alert">{signInError}</p>}
    </main>
  );
}
