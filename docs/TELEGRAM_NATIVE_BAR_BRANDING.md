# Telegram Mini App branding: native minimized bar, no token rotation

## Verified distinction

- The HTML browser title is **Київ Радар** (short legacy title restored).
- The Telegram **open Mini App** header/background/bottom bar can be themed with official WebApp methods.
- The Telegram **minimized Mini App Bar** is owned by the Telegram client. It can show the bot identity independently of HTML/CSS/JS. There is no documented API to remove native text or @username from this minimized surface.
- The live bot is currently referenced as `@prostov_shrink_bot`. Never replace this username in links or rotate the token merely to restyle the tab.

## Safe bot identity check — existing VPS credentials only

Use the one-time helper from a trusted shell on the existing VPS. The helper does not run automatically, prints no token, and refuses to change another bot.

```bash
python3 scripts/telegram_branding.py --check --env-file /opt/agent-bot/.env
```

After confirming the current profile, only an authorized operator can set the **display name** to `Київ Радар` using existing credentials:

```bash
python3 scripts/telegram_branding.py --apply --env-file /opt/agent-bot/.env
```

This calls Bot API `setMyName` for the default, Ukrainian and Russian languages and re-reads each value to verify. It does **not** alter @username, main Mini App title, profile photo, token, menu button, or backend. If the filename is not present on VPS, deploy the reviewed helper first; do not paste tokens into chat or GitHub.

## BotFather-only steps

From the owning Telegram account open [@BotFather](https://t.me/BotFather), run `/mybots`, select `@prostov_shrink_bot` and inspect:

1. **Edit Bot → Name**: should be `Київ Радар`.
2. **Configure Mini App / Edit Mini App**: check the actual Mini App title and launch link; use `Київ Радар` as the title without changing URL.
3. **Username**: if the Telegram client explicitly shows `@prostov_shrink_bot` in its native minimized tab, changing **display name** may not remove it. Username changes require bot-owner control through BotFather and can break old links, so must be planned, not guessed.
4. Reopen from the same launch route; compare the expanded app against the minimized bar on real Telegram Android/iOS.

A browser automation test cannot certify a native minimized tab's appearance. Do not mark this issue resolved on CI alone.

Official references: https://core.telegram.org/bots/api#setmyname and https://core.telegram.org/bots/webapps.
