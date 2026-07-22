# Setting up billing (Razorpay) — owner's guide

Shotvi charges for the **Studio Plan** using [Razorpay](https://razorpay.com)
Subscriptions (monthly, recurring). Razorpay was chosen because it supports
**UPI**, the way most Indian creators pay. This guide assumes you have never
used Razorpay before.

Until you finish this, the app runs **normally without billing**: leave the
Razorpay env vars unset and the sidebar shows a "Billing not configured" card
instead of an Upgrade button. Nothing crashes.

> ## ⚠️ Read this first: TEST MODE vs LIVE MODE
>
> Razorpay has two completely separate modes, each with its own keys:
>
> - **Test Mode** — fake payments, the full flow works end to end, **available
>   instantly, no verification needed.** Build and test everything here first.
> - **Live Mode** — real money. Requires **business KYC verification**
>   (PAN, bank account, business details). Razorpay can take **several days**
>   to approve it, and you cannot take real payments until they do.
>
> **Do all of the setup and testing below in TEST MODE.** Only switch to Live
> keys once KYC is approved and you're ready to charge real cards. The steps
> are identical in both modes — only the keys differ.

Total time in test mode: ~20 minutes.

---

## 1. Create a Razorpay account

1. Go to <https://dashboard.razorpay.com/signup> and sign up with your email.
2. You'll land in the dashboard. In the top bar there is a **Test Mode /
   Live Mode** toggle — **switch it to Test Mode** now and keep it there for
   all of the following steps.
3. You can start the KYC/business-verification process in the background
   (**Account & Settings → Website and app details / KYC**) so Live Mode is
   ready later — but you do **not** need it to finish this guide.

## 2. Get your Test API keys

1. In Test Mode, go to **Account & Settings → API Keys** (or
   **Settings → API Keys**).
2. Click **Generate Test Key**.
3. Copy both values shown:
   - **Key Id** — looks like `rzp_test_XXXXXXXXXXXXXX`. Safe to expose to the
     browser.
   - **Key Secret** — shown only once. Copy it now and store it safely. This
     is server-only — never put it in the frontend.

## 3. Create the Studio Plan

The **price lives on this plan**, not in the code — changing the price later is
a one-field edit here, nothing in the app changes.

1. In Test Mode, go to **Subscriptions → Plans → Create Plan** (Subscriptions
   may be under the left "Payment Products" menu; enable it if prompted — no
   KYC needed in test mode).
2. Fill in:
   - **Billing frequency**: **Monthly**, interval **1** (every 1 month).
   - **Plan name**: `Studio Plan`.
   - **Amount**: your price. The app currently *displays* **₹499/mo** as a
     placeholder — set the real amount here and update the display string once
     (see "Changing the price" below) so they match.
   - **Currency**: INR.
3. Save. Open the plan and copy its **Plan Id** — looks like
   `plan_XXXXXXXXXXXXXX`.

## 4. Set up the webhook

The webhook is how Razorpay tells the backend "this user just paid / cancelled"
so their plan status updates automatically.

1. Your backend must be reachable from the internet for Razorpay to call it.
   - Deployed: use your real API URL.
   - Local testing: run a tunnel, e.g. `ngrok http 8000`, and use the
     `https://…ngrok…` URL it prints.
2. In Test Mode, go to **Account & Settings → Webhooks → Add New Webhook**.
3. **Webhook URL**: `<your-backend-base-url>/billing/webhook`
   (e.g. `https://abcd-1234.ngrok-free.app/billing/webhook`).
4. **Secret**: type any strong random string and **copy it** — this becomes
   `RAZORPAY_WEBHOOK_SECRET`. (Razorpay signs each webhook with it; the backend
   rejects any call whose signature doesn't match, so unsigned/forged calls
   can never change anyone's plan.)
5. **Active events** — tick at least these four:
   - `subscription.activated`
   - `subscription.charged`
   - `subscription.cancelled`
   - `subscription.halted`
   (The backend also understands `subscription.completed` and
   `subscription.expired` if you tick them; anything else is safely ignored.)
6. Save.

## 5. Fill in the env file

Add these to the backend `.env` in the repo root (see `.env.example`):

```
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXXX
RAZORPAY_KEY_SECRET=<your test key secret>
RAZORPAY_WEBHOOK_SECRET=<the secret you typed in step 4.4>
RAZORPAY_PLAN_ID=plan_XXXXXXXXXXXXXX
```

Restart the FastAPI server. Nothing is needed in `frontend/.env` — the browser
gets the public key id from the backend when checkout starts.

To confirm it's live: sign in, and the sidebar card should now show
**"Upgrade to Studio Plan — ₹499/mo, billed monthly"** with an Upgrade button
(instead of "Billing not configured").

## 6. Test the whole flow (test mode)

1. Sign in to the app, click **Upgrade** in the sidebar. The Razorpay Checkout
   modal opens.
2. Pay with a **test instrument** (no real money):
   - **UPI**: enter `success@razorpay` as the UPI id.
   - **Card**: `4111 1111 1111 1111`, any future expiry, any CVV, any name.
   See <https://razorpay.com/docs/payments/payments/test-card-details/> for
   more test instruments.
3. Complete payment. Within a second or two the sidebar card flips to
   **"Studio Plan — Active"** (the app polls status after checkout; the flip
   itself is driven by the `subscription.activated` webhook).
4. Click **Cancel plan** → confirm. Razorpay processes the cancellation and the
   `subscription.cancelled` webhook flips the card back to Free.
5. If the status doesn't change, check:
   - The webhook shows **delivered** in **Webhooks → (your webhook) → Recent
     Deliveries** (a 400 there means the secret in `.env` doesn't match the one
     you set on the webhook).
   - The backend log prints a line like
     `[billing] subscription.activated → user <id> is now studio/active`.

## Going live (later, after KYC)

Once Razorpay approves your business KYC:

1. Switch the dashboard to **Live Mode** and repeat steps 2–4 to get **Live**
   keys, a **Live** plan id, and a **Live** webhook (pointing at your deployed
   `/billing/webhook`, not ngrok).
2. Replace the four `RAZORPAY_*` values in the production `.env` with the Live
   ones and restart. That's the only change — no code edits.

## Changing the price

The authoritative amount is the Razorpay Plan (step 3). Two things to keep in
sync:

1. The **Plan amount** in the Razorpay dashboard — the amount actually charged.
2. The **display string** shown in the UI — one constant,
   `STUDIO_PLAN["price_display"]` in [`api/billing.py`](api/billing.py). Update
   this string to match, and the sidebar reflects it everywhere automatically.

(Razorpay plans are immutable once created; to change the charged amount you
create a *new* plan and swap `RAZORPAY_PLAN_ID`. Existing subscribers stay on
their old plan until they resubscribe — standard Razorpay behaviour.)

## How it works (for later phases)

- Plan status hangs off the same Supabase user id that owns jobs (Build 1). It
  lives in Redis (`user:<id>`, no expiry) — deliberately minimal; a dedicated
  subscriptions table belongs to the later Supabase-Postgres phase.
- The backend is the source of truth: the browser never sets plan status. Only
  a signature-verified webhook from Razorpay flips a user between free and paid.
- **This build gates no features.** It only records *who* is paid
  (`plan == "studio"`), so a future real feature can check that in one line.
  The marketing copy that used to be in the sidebar ("4K exports, team seats,
  API access") describes features that **do not exist yet** — none of them are
  built or restricted.
