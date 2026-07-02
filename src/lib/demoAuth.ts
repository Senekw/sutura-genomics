// Client-side gate for the product demo flow (/demo/login → dashboard → …).
// This is a scripted product walkthrough, NOT real authentication — the single
// accepted credential lives here on the client on purpose so prospects can try
// the flow. Never guard anything sensitive with this.
export const DEMO_USERNAME = "suturagenomics1010101";
export const DEMO_PASSWORD = "SpatialBioOrg";

const STORAGE_KEY = "sutura_demo_authed";

export function checkCredentials(username: string, password: string): boolean {
  return username.trim() === DEMO_USERNAME && password === DEMO_PASSWORD;
}

export function signIn(): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(STORAGE_KEY, "1");
  }
}

export function signOut(): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(STORAGE_KEY);
  }
}

export function isAuthed(): boolean {
  if (typeof window === "undefined") return false;
  return window.sessionStorage.getItem(STORAGE_KEY) === "1";
}
