# מדריך הפעלה מלא — צעד אחר צעד

> זמן כולל: ~40 דקות. בסוף כל שלב כתוב "✔ מה אמור לקרות" כדי שתדע שהצלחת.

## שלב 0 — הקוד ב-GitHub (2 דק')

הקוד יושב בענף `claude/agent-task-continuation-fbga9x` בריפו שלך.

1. פתח: https://github.com/trtrhtv/agent/branches
2. או שתמזג את הענף ל-main (כפתור New pull request → Merge), או שפשוט תבחר את הענף הזה ישירות ב-Railway בשלב 5 — שתי הדרכים תקינות.

✔ אתה רואה את הקבצים (app/, migrations/, README) בענף.

## שלב 1 — Supabase: מסד הנתונים (7 דק', חינם)

1. הירשם/התחבר: https://supabase.com/dashboard
2. **New project** → שם: `trendmill` → בחר סיסמת DB (שמור אותה) → Region: `Central EU` או `US East` → Create.
3. המתן ~2 דקות שהפרויקט יעלה.
4. בתפריט השמאלי: **SQL Editor** → **New query** → הדבק את תוכן `migrations/001_init.sql` → **Run**. חזור על זה לכל קובץ לפי הסדר: `001, 002, 003, 004, 005, 006`.
5. בתפריט: **Project Settings** (גלגל שיניים) → **API**:
   - העתק את **Project URL** → זה `SUPABASE_URL`
   - העתק את **service_role** key (תחת Project API keys, לא את anon!) → זה `SUPABASE_SERVICE_KEY`

✔ ב-**Table Editor** אתה רואה את הטבלאות: opportunities, product_jobs, performance, events, insights, competitor_snapshots, trend_links, seasonal_profiles.

## שלב 2 — בוט טלגרם (5 דק', חינם)

1. פתח בטלגרם: https://t.me/BotFather
2. שלח `/newbot` → תן שם (למשל `TrendMill`) → תן username שנגמר ב-bot (למשל `trendmill_xyz_bot`).
3. BotFather יחזיר טוקן בפורמט `123456789:AAF...` → זה `TELEGRAM_BOT_TOKEN`.
4. **שלח הודעה כלשהי לבוט החדש שלך** (חפש אותו לפי ה-username, לחץ Start).
5. פתח בדפדפן (החלף את TOKEN):
   `https://api.telegram.org/botTOKEN/getUpdates`
   חפש `"chat":{"id":123456789` → המספר הזה הוא `TELEGRAM_OWNER_CHAT_ID`.

✔ קיבלת טוקן ומספר chat id.

## שלב 3 — OpenRouter: מפתח ה-AI (3 דק')

1. הירשם: https://openrouter.ai
2. מפתח: https://openrouter.ai/settings/keys → **Create Key** → העתק → זה `OPENROUTER_API_KEY`.
3. קרדיט: https://openrouter.ai/settings/credits → טען $5 (יספיק לחודשים; יש עמלת טעינה קטנה).

✔ יש לך מפתח `sk-or-...` ויתרה חיובית.

## שלב 4 — Gumroad: החנות (7 דק', חינם)

1. פתח חשבון מוכר: https://gumroad.com → Sign up → השלם פרופיל בסיסי + חיבור payout (בנק/PayPal — נדרש כדי לקבל כסף).
2. טוקן API: https://app.gumroad.com/settings/advanced → תחת **Applications** → **Create application** (שם: TrendMill, כתובת כלשהי) → **Generate access token** → זה `GUMROAD_ACCESS_TOKEN`.

✔ יש לך access token.

## שלב 5 — Railway: השרת (15 דק', $5/חודש)

1. הירשם עם GitHub: https://railway.app
2. **New Project** → **Deploy from GitHub repo** → אשר גישה לריפו `trtrhtv/agent` → בחר אותו.
3. ב-Settings של השירות שנוצר: **Branch** → בחר את הענף עם הקוד. **Start Command**:
   `uvicorn app.server:app --host 0.0.0.0 --port $PORT`
4. **Variables** (בפרויקט, כדי שישותפו): הוסף את כל אלה —
   ```
   SUPABASE_URL=...
   SUPABASE_SERVICE_KEY=...
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_OWNER_CHAT_ID=...
   TELEGRAM_WEBHOOK_SECRET=<המצא מחרוזת אקראית ארוכה>
   OPENROUTER_API_KEY=...
   GENERATION_MODEL=anthropic/claude-sonnet-4-6
   ROUTINE_MODEL=deepseek/deepseek-v3.2
   GUMROAD_ACCESS_TOKEN=...
   UPLOAD_STRATEGY=api
   TRENDMILL_NICHES=spreadsheets,trader_tools
   ```
5. צור עוד 3 שירותים מאותו ריפו (בפרויקט: **+ New** → GitHub Repo → אותו ריפו), ולכל אחד ב-Settings קבע Start Command + **Cron Schedule**:
   | שירות | Start Command | Cron Schedule |
   |---|---|---|
   | scan | `python scan.py` | `23 6 * * *` |
   | learn | `python learn.py` | `41 6 * * 1` |
   | foresight | `python foresight.py` | `19 5 3 * *` |
6. בשירות ה-web: **Settings → Networking → Generate Domain** → העתק את הכתובת (`https://....up.railway.app`).

✔ שירות ה-web מציג Deploy מוצלח, ו-`https://<הכתובת>/health` מחזיר `{"status":"ok"}`.

## שלב 6 — חיבור הטלגרם לשרת (2 דק')

במחשב שלך (עם python + הריפו, ו-`.env` מלא):
```bash
pip install httpx python-dotenv
python scripts/set_webhook.py https://<הכתובת-מ-Railway>.up.railway.app
```
(או ידנית בדפדפן: `https://api.telegram.org/botTOKEN/setWebhook?url=https://<הכתובת>/telegram/webhook&secret_token=<הסוד>`)

✔ התגובה מכילה `"ok":true`. שלח `/status` לבוט — הוא עונה.

## שלב 7 — הכרעת אסטרטגיית ההעלאה (5 דק')

במחשב שלך:
```bash
GUMROAD_ACCESS_TOKEN=<הטוקן> python spike/gumroad_create_spike.py
```
- `VERDICT: STRATEGY_A` → הכל טוב, `UPLOAD_STRATEGY=api` נשאר.
- `VERDICT: STRATEGY_B` → ב-Railway שנה `UPLOAD_STRATEGY=playwright` והוסף `GUMROAD_EMAIL` + `GUMROAD_PASSWORD`.

✔ יש לך VERDICT ומשתני הסביבה תואמים.

## שלב 8 — הצתה 🚀 (5 דק')

ב-Railway, בשירות foresight: **Deployments → ⋮ → Restart** (הרצה ידנית ראשונה), ואז אותו דבר בשירות scan. לחלופין מהמחשב: `python foresight.py` ואז `python scan.py` עם `.env` מלא.

✔ תוך דקות מגיעות לטלגרם שתי הודעות דייג'סט (אחת לכל נישה). לחץ ✅ על מוצר → תוך ~3 דקות מגיעים גלריית תמונות + קובץ + ציון איכות → לחץ "✅ אשר והעלה" → מגיע לינק חי ל-Gumroad.

---

## תקלות נפוצות

| סימפטום | סיבה סבירה | פתרון |
|---|---|---|
| אין דייג'סט אחרי scan | משתנה סביבה חסר/שגוי | Railway → Deployments → Logs של scan; כל שגיאה גם נשלחת לטלגרם |
| הבוט לא עונה ל-/status | webhook לא נרשם / סוד לא תואם | חזור על שלב 6; ודא ש-`TELEGRAM_WEBHOOK_SECRET` זהה |
| העלאה נכשלת עם 404 | Gumroad API לא תומך ביצירה | זה בדיוק STRATEGY_B — שלב 7 |
| דייג'סט ריק/דל | Etsy חסם סקרייפינג באותו יום | תקין — fail-soft; ינסה שוב מחר, טרנדים עדיין עובדים |
