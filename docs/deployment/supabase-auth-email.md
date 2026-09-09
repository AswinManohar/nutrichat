# Mealsy — Auth email configuration runbook

How the sign-up / sign-in emails get their links and their branding. All four
settings below live in the **hosted auth dashboard** and none of them can be
applied from this repo — there is no `config.toml`, no CLI installed, and no
`SUPABASE_ACCESS_TOKEN` in the environment. This page is the checklist an
operator works through by hand.

> Naming note: as elsewhere in `docs/deployment/`, the infra identifiers keep
> the old "nutrichat" name (Netlify site `nutrichat-frontend`, deploy URLs).
> The product is **Mealsy**. That mismatch is intentional.

The email HTML itself is version-controlled at
[`supabase/templates/`](../../supabase/templates/) — that directory's README is
the source of truth for the markup and the template variables.

---

## What breaks if this is skipped

| Setting | Symptom when wrong |
|---|---|
| Site URL | Every link in every auth email points at `http://localhost:5173` — dead for real users |
| Redirect URLs | A correct `emailRedirectTo` is rejected and silently falls back to Site URL |
| Templates | Emails carry stock vendor branding, not Mealsy |
| Custom SMTP | **Sign-up only works for org team members.** Everyone else gets *Email address not authorized* |

The last row is a hard gate, not a polish item: without custom SMTP the product
cannot onboard a single external user.

---

## 1. Site URL

**Dashboard → Authentication → URL Configuration → Site URL**

```
https://nutrichat-frontend.netlify.app
```

This is the fallback every template resolves to when the client does not pass
an explicit redirect. It is currently the Vite dev default, which is the whole
reason confirmation links land on localhost.

---

## 2. Redirect URLs allowlist

**Dashboard → Authentication → URL Configuration → Redirect URLs**

Add both:

```
https://nutrichat-frontend.netlify.app/**
http://localhost:5173/**
```

The wildcard suffix matters — the allowlist is matched against the full
redirect URL, so a bare origin will not match `/auth/callback?code=…`. Keep the
localhost entry: without it, local development cannot complete an email flow.

Any value the frontend passes as `emailRedirectTo` (on `signUp`) or `redirectTo`
(on `resetPasswordForEmail`) must match an entry here, or it is discarded and
Site URL is used instead — which fails silently and looks like the redirect
code never ran.

---

## 3. Email templates

**Dashboard → Authentication → Emails**

Paste each file from `supabase/templates/` into its matching tab:

| File | Tab | Subject to set |
|---|---|---|
| `confirm-signup.html` | Confirm signup | `Confirm your email address` |
| `magic-link.html` | Magic Link | `Your Mealsy sign-in link` |
| `reset-password.html` | Reset Password | `Reset your Mealsy password` |
| `email-change.html` | Change Email Address | `Confirm your new Mealsy email address` |

Paste the file whole, HTML comment header included — comments do not render,
and they keep the dashboard copy traceable to the repo. Set the subject line in
the field above the editor; it is stored separately from the body.

**Edit the repo files, then paste — never the other way round.** A change made
only in the dashboard is invisible to review and will be overwritten by the
next paste.

Templates are independent of SMTP: they can be pasted and previewed today,
before section 4 is unblocked.

---

## 4. Custom SMTP — sender name "Mealsy"

**Dashboard → Project Settings → Authentication → SMTP Settings**

This is the one item that **cannot be completed yet**. Two constraints from the
[custom SMTP guide](https://supabase.com/docs/guides/auth/auth-smtp):

**Delivery is restricted to team members.** Quoting the guide directly: "Unless
you configure a custom SMTP server for your project, Supabase Auth will refuse
to deliver messages to addresses that are not part of the project's team… All
other addresses will fail with the error message *Email address not
authorized.*" The built-in sender is also rate-limited — "Currently this value
is set to 2 messages per hour" — and the guide states plainly that it "is not
meant for production use."

**The From address is not ours to set until custom SMTP is on.** Sender email
and sender name are custom-SMTP fields: the guide introduces "a default From
address, usually something like `no-reply@example.com`" and `smtp_sender_name`
only as inputs to the custom SMTP setup, and the dashboard exposes no From /
sender-name field while the built-in service is in use. Until then, mail goes
out under the platform's own noreply address, whatever the body says. (Noted
for accuracy: the guide does not spell out "the built-in From address cannot be
changed" in those words — this is what its framing and the dashboard UI leave
available.)

### The blocker: no sending domain

Custom SMTP needs a From address on a domain we control and can prove we
control. Resend, Postmark and SES all verify a sending domain by DNS record.
We have no such domain:

```bash
netlify api listSites --data '{}' \
  | python3 -c "import json,sys;[print(s['name'],s.get('custom_domain')) for s in json.load(sys.stdin)]"
# -> nutrichat-frontend None
```

`nutrichat-frontend.netlify.app` is a Netlify-owned subdomain — we cannot add
DNS records to it, so it can never be verified as a sending domain.

**A domain has to be bought before the sender can say Mealsy.** Everything in
sections 1–3 ships without it, and section 1 alone stops the dead-localhost
links.

### Once a domain exists

1. Add the domain to a sending provider and complete its DNS verification.
2. Set up SPF, DKIM and DMARC for it. The guide lists these under best
   practices rather than hard requirements, but skipping them means the mail
   lands in spam.
3. Fill in the dashboard SMTP form:

   | Field | Value |
   |---|---|
   | Sender email | `no-reply@<domain>` |
   | Sender name | `Mealsy` |
   | Host / Port | from the provider (usually port 587) |
   | Username / Password | from the provider |

4. Raise the rate limit. Enabling custom SMTP applies "a low rate-limit of 30
   messages per hour" by default — adjust it under Authentication → Rate Limits.
5. **Disable click/open tracking at the provider.** Tracking rewrites outbound
   links, which breaks the single-use verify URL. The templates docs call this
   out explicitly.

---

## Verify

After sections 1–3, with an org team member's address (the only one the
built-in sender will accept):

1. Sign up on <https://nutrichat-frontend.netlify.app> with that address.
2. Check the email: Mealsy wordmark, sage-green button, a visible raw link
   underneath it, and no mention of the auth vendor in the copy.
3. Click through. The link must land on `nutrichat-frontend.netlify.app`, not
   `localhost:5173`.
4. Copy the raw fallback link into a different browser and confirm it behaves
   the same as the button. This is the path that has to work when a client
   strips the button.

If step 3 still lands on localhost, Site URL did not save, or the frontend is
passing an `emailRedirectTo` that is not in the allowlist and is being ignored.

Note that the fallback link's hostname is on the auth provider's domain until a
platform custom domain is configured — the copy is ours, the verify hostname is
not. `supabase/templates/README.md` documents the two ways to change that and
why neither is done yet.

---

## Related

- [`supabase/templates/README.md`](../../supabase/templates/README.md) — the
  template markup, the verified variable list, and the editing rules
- [`deploy-guide.md`](deploy-guide.md) — how the frontend and backend ship
- Upstream refs:
  [email templates](https://supabase.com/docs/guides/auth/auth-email-templates),
  [custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp)
