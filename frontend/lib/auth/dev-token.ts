// Dev-mode JWT minting (contracts C1; research D2). Mirrors the exact contract
// of backend/app/core/security/dev.py: HS256, aud=contextly-dev, sub=user id.
import { SignJWT } from "jose";
import { createHash } from "crypto";
import { DEV_AUDIENCE, getDevJwtSecret } from "./session";

/** Deterministic v5-style UUID from an email — stable user across sessions. */
export function devUserIdFromEmail(email: string): string {
  const hash = createHash("sha256").update(email.trim().toLowerCase()).digest();
  const bytes = hash.subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export async function mintDevToken(email: string): Promise<string> {
  return new SignJWT({ email })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(devUserIdFromEmail(email))
    .setAudience(DEV_AUDIENCE)
    .setIssuedAt()
    .setExpirationTime("1h")
    .sign(new TextEncoder().encode(getDevJwtSecret()));
}