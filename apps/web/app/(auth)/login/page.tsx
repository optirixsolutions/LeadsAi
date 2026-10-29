import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthCard } from "@/features/auth/auth-card";
import { LoginForm } from "@/features/auth/login-form";
import { safeNext } from "@/features/auth/schemas";
import { optionalMe } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  if (await optionalMe()) redirect(safeNext(next));
  const registerHref = next ? `/register?next=${encodeURIComponent(next)}` : "/register";

  return (
    <AuthCard
      title="Sign in"
      description="Welcome back."
      footer={
        <>
          New to SalesIQ?{" "}
          <Link href={registerHref} className="text-accent hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <LoginForm next={next} />
      <p className="mt-4 text-center text-xs">
        <Link href="/forgot-password" className="text-fg-muted hover:text-fg">
          Forgot your password?
        </Link>
      </p>
    </AuthCard>
  );
}
