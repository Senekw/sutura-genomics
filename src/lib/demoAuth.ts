// Client-side gate for the product demo flow (/demo/login → dashboard → …).
// This is a scripted product walkthrough, NOT real authentication — the accepted
// demo credentials live here on the client on purpose so prospects can try the
// flow. Never guard anything sensitive with this. You can sign in with either
// the username or (for the first account) its email.
const DEMO_CREDENTIALS: { logins: string[]; password: string }[] = [
  { logins: ["suturagenomics1010101", "suturagenomics@gmail.com"], password: "SpatialBioOrg" },
  { logins: ["SGYC1234"], password: "spatialbioSGYC" },
];

const STORAGE_KEY = "sutura_demo_authed";

export function checkCredentials(usernameOrEmail: string, password: string): boolean {
  const id = usernameOrEmail.trim().toLowerCase();
  return DEMO_CREDENTIALS.some(
    (c) => c.logins.some((l) => l.toLowerCase() === id) && c.password === password
  );
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
