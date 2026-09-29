# Mealsy auth email templates

**These four files are the source of truth for the auth emails.** Edit them
here, review the diff, then paste the result into the hosted project's
dashboard at **Authentication → Emails**. Nothing in this repo applies them
automatically — see [Why paste?](#why-paste) below.

Operator runbook (Site URL, redirect allowlist, SMTP):
[`docs/deployment/supabase-auth-email.md`](../../docs/deployment/supabase-auth-email.md).

| File | Dashboard tab | Config key | Suggested subject |
|---|---|---|---|
| `confirm-signup.html` | Confirm signup | `confirmation` | Confirm your email address |
| `magic-link.html` | Magic Link | `magic_link` | Your Mealsy sign-in link |
| `reset-password.html` | Reset Password | `recovery` | Reset your Mealsy password |
| `email-change.html` | Change Email Address | `email_change` | Confirm your new Mealsy email address |

The "Config key" column is the name the same template goes by in the
`mailer_templates_<key>_content` Management API field and in
`[auth.email.template.<key>]`. It is listed for identification only — neither
path is wired up here.

---

## Template variables

Verified against the current docs, not from memory. Source:
<https://supabase.com/docs/guides/auth/auth-email-templates> (fetch the raw
markdown by appending `.md` to the path). Descriptions below are quoted from
that page's *Terminology* table.

| Variable | Doc description (quoted) |
|---|---|
| `{{ .ConfirmationURL }}` | "Contains the confirmation URL. For example, a signup confirmation URL would look like: `https://project-ref.supabase.co/auth/v1/verify?token={{ .TokenHash }}&type=email&redirect_to=https://example.com/path`." |
| `{{ .Token }}` | "Contains a 6-digit One-Time-Password (OTP) that can be used instead of the `{{ .ConfirmationURL }}`." |
| `{{ .TokenHash }}` | "Contains a hashed version of the `{{ .Token }}`. This is useful for constructing your own email link in the email template." |
| `{{ .SiteURL }}` | "Contains your application's Site URL. This can be configured in your project's authentication settings." |
| `{{ .RedirectTo }}` | "Contains the redirect URL passed when `signUp`, `signInWithOtp`, `signInWithOAuth`, `resetPasswordForEmail` or `inviteUserByEmail` is called." |
| `{{ .Email }}` | "Contains the original email address of the user. Empty when trying to link an email address to an anonymous user." |
| `{{ .NewEmail }}` | "Contains the new email address of the user. This variable is only supported in the 'Change email address' template." |
| `{{ .Data }}` | "Contains metadata from `auth.users.user_metadata`. Use this to personalize the email message." |

### Which apply where

The docs scope only two of these explicitly, by naming the one template each
belongs to. Everything else in the table is documented generically, i.e. it is
available in every auth template:

- `{{ .NewEmail }}` — **Change email address only.**
- `{{ .OldEmail }}` — Email address changed *notification* only. Not used here;
  we do not currently customise the security-notification templates.
- `{{ .ConfirmationURL }}`, `{{ .Token }}`, `{{ .TokenHash }}`, `{{ .SiteURL }}`,
  `{{ .RedirectTo }}`, `{{ .Email }}`, `{{ .Data }}` — no per-template
  restriction is documented; each is valid in all four templates here.

Caveat worth knowing: `{{ .RedirectTo }}` is only populated when the caller
actually passed a redirect (`emailRedirectTo` on `signUp`, `redirectTo` on
`resetPasswordForEmail`, …). If no redirect is passed it falls back to the
project's **Site URL**. That fallback is exactly the localhost bug these
templates were written for — fixing it is a Site URL + client-code change, not
a template change.

### What these templates actually use

| Template | Variables used |
|---|---|
| `confirm-signup.html` | `{{ .ConfirmationURL }}` |
| `magic-link.html` | `{{ .ConfirmationURL }}` |
| `reset-password.html` | `{{ .ConfirmationURL }}` |
| `email-change.html` | `{{ .ConfirmationURL }}`, `{{ .Email }}`, `{{ .NewEmail }}` |

`{{ .ConfirmationURL }}` is used deliberately rather than a hand-built
`token_hash` link: it works with the default verify flow today and does not
depend on the app implementing any particular callback contract. See
[Known trade-offs](#known-trade-offs) for the alternative and when to switch.

---

## House rules for editing

These are email templates, not web pages. Anything below will break in some
client, so don't reach for it:

- **Tables for layout**, `role="presentation"`, fixed 600px max width.
- **Inline `style` attributes only.** No `<style>` block, no external
  stylesheet, no CSS classes.
- **No webfonts.** Georgia for display (stands in for Fraunces), Helvetica /
  Arial for body (stands in for Inter).
- **No JavaScript. No external images.** There is no CDN for this project, so
  the mark is a CSS-drawn rounded square with an "M" plus a text wordmark —
  nothing to hotlink and nothing to be blocked by image-blocking clients.
- **Always keep the raw-URL fallback line.** Every template prints the full
  link as selectable text underneath the button. Plenty of clients strip or
  mangle button markup, and a link the user cannot click is the exact bug we
  set out to fix.
- **The rendered body must never say the name of our auth vendor.** Users are
  signing in to Mealsy; the infrastructure behind it is not their business.
  Grep the visible copy before pasting.

### Palette

Resolved from `frontend/src/index.css` (Tailwind v4 `@theme` block — there is
no `tailwind.config.js` in this project) and written inline as hex:

| Token | Hex | Used for |
|---|---|---|
| `surface` | `#faf9f6` | page background |
| `paper` | `#ffffff` | card background |
| `sand` | `#f2ede4` | inset panel (email-change from/to block) |
| `sand-border` | `#e5e0d8` | card border, divider |
| `sage-deep` | `#516050` | wordmark, button fill, links |
| `ink` | `#1b1c1a` | headings |
| `ink-soft` | `#3a424a` | body copy |
| `muted` | `#747872` | fine print, footer |

`sage` (`#7d8c7b`) and `sage-soft` (`#9db0a0`) are the lighter brand greens;
they are intentionally unused here because neither clears 4.5:1 contrast
against white for text or as a button fill behind white text. `sage-deep` does.

---

## Why paste?

This claim was checked rather than assumed. For a **hosted** project there are
exactly three ways to set template content, and only one of them is available
to this repo today:

1. **Dashboard → Authentication → Emails.** What we use. The docs are explicit
   that this is the hosted path: "Edit templates on the Email Templates page in
   the dashboard."
2. **`supabase/config.toml` + `content_path`.** *Does not apply to us.* The
   docs state the dashboard builder "**does not apply** when running local
   development with CLI or self-hosted Supabase. Customize templates in
   `supabase/config.toml` and local HTML files instead" — the direction we need
   is the reverse, and the companion page opens with "Customize the email
   templates **for local development** by editing the `config.toml` file …
   For hosted projects, use the Email Templates page in the dashboard."
   ([customizing-email-templates](https://supabase.com/docs/guides/local-development/customizing-email-templates))
   There is also no `config.toml` and no CLI installed here (`which supabase`
   → nothing).
3. **Management API** — `PATCH /v1/projects/{ref}/config/auth` with
   `mailer_templates_confirmation_content` and friends. This *would* let a
   script push these files to the hosted project, so "there is no way to sync
   from a repo" would be too strong a statement. What blocks it is access, not
   capability: it needs a personal access token in `SUPABASE_ACCESS_TOKEN`,
   which this environment does not have and which we would not want committed.

So: **paste by hand**, and treat these files as the reviewed original. If a
personal access token is ever provisioned in CI, option 3 is the upgrade path
and these files can be pushed verbatim.

The HTML comment header at the top of each file is safe to paste — comments are
not rendered — and keeps the dashboard copy traceable back to this directory.

---

## Known trade-offs

Two things here are deliberate compromises. Both are recorded so nobody
"fixes" them by accident.

**1. The fallback URL is on the auth host, not on `mealsy` anything.**
`{{ .ConfirmationURL }}` expands to
`https://<project-ref>.supabase.co/auth/v1/verify?…`. Our *copy* never names
the vendor, but that interpolated hostname is visible in the fallback line and
in the browser during the redirect. Two ways to remove it, neither free:

- Set up a **custom domain** for the auth server (a paid platform add-on) so
  the verify URL becomes `auth.<our-domain>`; or
- build the link ourselves against our own frontend:
  `{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=<type>`
  with `type` being `signup`, `magiclink`, `recovery`, `email_change`
  respectively, and have `/auth/callback` call
  `supabase.auth.verifyOtp({ token_hash, type })`.

  Do **not** make this swap until `/auth/callback` demonstrably handles
  `token_hash`. At the time of writing, `frontend/src/pages/AuthCallbackPage.tsx`
  reads the implicit-flow URL *fragment* (`#access_token=…`, `#error_code=…`)
  and has no `token_hash` branch — which is precisely what
  `{{ .ConfirmationURL }}` produces after it redirects. Switching the link
  format without adding a `verifyOtp` branch first would break every auth email
  at once.

**2. The footer carries the tagline, against the vendor's deliverability
advice.** The SMTP guide's anti-spam best practices say to "avoid taglines or
other short-form marketing material in authentication messages" and warn that
describing what the app does is "especially apparent if your project is related
to: Web3, Blockchain, **AI** …" — our tagline is *AI-Powered Macro Coaching &
Meal Logging*, which is squarely in that category. It is included because
branding was the requirement, kept to one 12px footer line, and it is the first
thing to delete if these emails start landing in spam.

**3. No `{{ .Token }}` OTP shown.** The docs note that some corporate scanners
(e.g. Microsoft Defender Safe Links) prefetch links and consume the
single-use token, producing "Token has expired or is invalid", and recommend
offering the 6-digit `{{ .Token }}` as an escape hatch. We do not show it,
because there is no screen in the app where a user could enter it. Add the
screen first, then add `{{ .Token }}` to these templates.

---

## Testing a change

There is no preview harness. To check a template renders:

1. Open the file in a browser to eyeball layout (the `{{ … }}` placeholders
   will show through literally — that is expected).
2. Paste into the dashboard and use **Send test email** if available, or
   trigger the real flow with a project-team address. Remember the built-in
   sender only delivers to organization team members and is rate-limited to
   2 messages per hour — see the runbook.
3. Check on a phone. The card is `max-width:600px` with `width:100%`, so it
   should reflow without horizontal scroll.
