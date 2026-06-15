# Tuning what NutriChat says — a guide for non-developers

Everything the agent **SAYS** (its tone, wording, examples) and how it
**DECIDES** (whether a message is a question or a meal being logged, what
counts as "junk food") is controlled by **one file**:

```
src/backend/config/tunables.yaml
```

You don't need to know how to code to make small wording changes here. Just
follow the steps below.

---

## 1. The sections you can safely edit

Open `src/backend/config/tunables.yaml` in a text editor and look for these
sections (use Find / Ctrl+F to jump to each one):

- **`prompts.coaching_response_system`** — controls how the agent answers
  nutrition questions: its tone, the rules it follows, and the format of
  its replies (including the meal-plan "recipe card" style).

- **`prompts.coaching_role_and_tone`** and **`prompts.coaching_hard_constraints`**
  — short blocks that set the agent's overall personality (encouraging,
  concise) and a few firm rules (e.g. never give medical advice, keep
  answers short).

- **`prompts.intent_system`** — controls how the agent decides whether a
  message is a QUESTION (coaching) or a food being LOGGED (meal entry),
  for tricky messages the quick word-list below doesn't catch.

- **`routing.log_signals`** and **`routing.query_signals`** — these are the
  word-lists the agent checks first to quickly tell "I'm logging food"
  (e.g. "i ate", "for breakfast") apart from "I'm asking a question"
  (e.g. "how much", "what is", "calories").

- **`prompts.query_parse_system`** — controls how the agent reads a
  question and figures out the time period (today/this week/etc.) and
  what nutrients it's about.

- **`prompts.extraction_system`** — controls how the agent reads a meal
  description and turns it into food items + quantities (includes the
  gram-conversion examples, e.g. "1 large egg=61g").

- **`junk`** section (`sugar_density_g`, `sat_fat_density_g`, `fiber_floor_g`)
  — these numbers set what counts as "junk food" for flags and coaching
  answers. These are NUMBERS, not text — only change them if you understand
  what they mean, and change them in small steps.

---

## 2. How to edit safely

1. Open `src/backend/config/tunables.yaml` in any text editor (e.g.
   Notepad, VS Code, TextEdit).
2. Use **Find** (Ctrl+F / Cmd+F) to jump to the section you want (e.g. type
   `coaching_response_system`).
3. Change **only the wording** inside the text — the sentences in quotes or
   in the indented text block under a `key:` label.
4. **Do not** delete or rename anything before the `:` — those are the
   labels the program looks for. Keep the same indentation (spacing) as the
   line above/below it.
5. Save the file.

### Example: making the coaching tone a bit warmer

Find `prompts.coaching_role_and_tone`. Before:

```yaml
  coaching_role_and_tone: |
    You are NutriChat, a nutrition coach. Be encouraging, concise,
    and grounded only in the user's own logged data and goals. Never invent
    numbers — if data is missing, say so.
```

After (only the wording inside the block changed — labels and indentation
stayed the same):

```yaml
  coaching_role_and_tone: |
    You are NutriChat, a friendly nutrition coach. Be warm, upbeat,
    and grounded only in the user's own logged data and goals. Never invent
    numbers — if data is missing, say so.
```

That's it — same structure, just different words.

---

## 3. How to publish your change

1. Open a terminal in the `nutrichat` project folder.
2. Run:

   ```
   bash scripts/deploy.sh
   ```

3. Wait about **2-3 minutes** for the deploy to finish.
4. Test your change in the app, or by chatting with the Telegram bot.

(You need to be logged into Railway for this — it's already set up on this
machine, so you shouldn't need to do anything extra.)

---

## 4. How to check it worked

- Send a test message (e.g. ask a nutrition question, or log a meal) and
  check that the wording/behavior matches what you expected.
- If it looks right — great, you're done!

---

## 5. If something looks wrong

Don't panic — nothing is lost:

- The previous wording is saved in the project's git history, so it can
  always be restored.
- Railway also keeps a history of previous deployments, so the live app can
  be **rolled back** to the version before your change from the Railway
  dashboard ("Rollback" button on a previous deployment).

If you're not sure how to undo a change, ask a developer, or use Railway's
dashboard to roll back to the last working deployment.
