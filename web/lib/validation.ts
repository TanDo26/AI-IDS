/**
 * Form rules, mirroring the API's (src/api/auth/schemas.py, security.py) so mistakes show before a
 * request is sent. The API checks again and stays the authority.
 */
import { z } from "zod";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const USERNAME = /^[A-Za-z0-9_.-]{3,64}$/;
export const PASSWORD_MIN_BYTES = 8;
export const PASSWORD_MAX_BYTES = 72;     // bcrypt's limit, counted in UTF-8 bytes (é = 2)

export function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).length;
}

const email = z.string().trim().toLowerCase().max(320, "Email is too long")
  .regex(EMAIL, "Enter a valid email address");

const newPassword = z.string().refine(
  (v) => utf8Bytes(v) >= PASSWORD_MIN_BYTES && utf8Bytes(v) <= PASSWORD_MAX_BYTES,
  `Use ${PASSWORD_MIN_BYTES}–${PASSWORD_MAX_BYTES} characters (accented letters count as two)`,
);

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Enter your password").max(1024),
});

export const signupSchema = z
  .object({
    email,
    username: z.string().trim().regex(USERNAME, "3–64 characters: letters, digits, _ . -"),
    password: newPassword,
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "The passwords don't match" });

export const passwordChangeSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current password").max(1024),
    new_password: newPassword,
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "The passwords don't match" })
  .refine((v) => v.new_password !== v.current_password, {
    path: ["new_password"], message: "Choose a password different from the current one",
  });

export type LoginForm = z.infer<typeof loginSchema>;
export type SignupForm = z.infer<typeof signupSchema>;
export type PasswordChangeForm = z.infer<typeof passwordChangeSchema>;
