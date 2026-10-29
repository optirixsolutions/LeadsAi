import { z } from "zod";

// Mirrors API limits (apps/api/app/core/security.py); the API re-validates everything.
export const MIN_PASSWORD = 12;
const MAX_PASSWORD = 256;

const email = z.string().trim().min(1, "Enter your email").pipe(z.email("Enter a valid email"));
const newPassword = z
  .string()
  .min(MIN_PASSWORD, `Use at least ${MIN_PASSWORD} characters`)
  .max(MAX_PASSWORD, "Password is too long");

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Enter your password"),
});

export const registerSchema = z.object({
  display_name: z.string().trim().max(200),
  email,
  password: newPassword,
});

export const forgotSchema = z.object({ email });

export const resetSchema = z
  .object({ new_password: newPassword, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, {
    path: ["confirm"],
    message: "Passwords do not match",
  });

export const changePasswordSchema = z
  .object({ current_password: z.string().min(1, "Enter your current password"), new_password: newPassword, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, {
    path: ["confirm"],
    message: "Passwords do not match",
  });

export const orgNameSchema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(200, "Name is too long"),
});

/** Only same-site relative paths are allowed as post-login destinations (no open redirect). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return "/";
  }
  return next;
}
