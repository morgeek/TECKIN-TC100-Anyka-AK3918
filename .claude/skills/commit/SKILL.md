---
name: commit
description: Stage and commit changes with a descriptive message following project conventions.
argument-hint: "[optional message prefix]"
disable-model-invocation: true
allowed-tools: Bash(git status) Bash(git diff*) Bash(git add *) Bash(git commit*)
---

Create a git commit for the current changes.

## Steps

1. Run `npm run check:web` to verify frontend and www are in sync. If it fails, run `npm run build:web` first, then retry.

2. Show what will be committed:
   ```bash
   git status
   git diff --stat HEAD
   ```

3. Stage relevant files (never `.env`, `*.conf` with real credentials, or large binaries):
   ```bash
   git add <files>
   ```

4. Write a concise commit message:
   - Format: `<type>: <short description>` where type is `feat`, `fix`, `chore`, `docs`, or `refactor`.
   - Focus on the *why*, not the *what*.
   - If `$ARGUMENTS` is provided, use it as the message prefix or type.
   - Add `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` as a trailer.

5. Commit:
   ```bash
   git commit -m "$(cat <<'EOF'
   <message>

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

6. Confirm with `git log --oneline -1`.
