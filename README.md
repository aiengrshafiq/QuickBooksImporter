# QuickBooks LPO/Invoice Importer

This project imports Invoice and LPO data from the QuickBooks Online API into your PostgreSQL database, handling suppliers, items, and attachments.

It is designed to be **idempotent**, meaning you can run it multiple times, and it will skip any records that have already been imported (based on Invoice/LPO number).

---

## **Part 1: Get QuickBooks Credentials (One-Time Setup)**

This is the most important part. You only need to do this once.

### Step 1. Create a QuickBooks Developer App

1.  Go to the [QuickBooks Developer Portal](https://developer.intuit.com/) and sign in.
2.  Go to the **Dashboard** and click **Create an app**.
3.  Select **QuickBooks Online and Payments**.
4.  Give your app a name (e.g., "My Database Importer").
5.  In the **Scopes** section, you MUST add *at least* the following:
    * `com.intuit.quickbooks.accounting`
6.  Click **Create app**.

### Step 2. Get Your Keys

1.  On your app's dashboard, go to the **Keys & OAuth** section.
2.  You will see your **Client ID** and **Client Secret**. You will need these.
3.  Find the **Redirect URIs** section. Click **Add URI**.
4.  Enter **`http://localhost:8000/callback`** exactly. This is what our script will use.
5.  **CRITICAL:** At the top of the page, switch from **Development** to **Production**. This will give you a *new* set of **Client ID** and **Client Secret** keys for your live data. Use these.

### Step 3. Fill Your `.env` File

1.  Create a file named `.env` in this directory.
2.  Copy the contents of `.env.example` into it.
3.  Fill in your **Database**, **Azure**, and the **QB_CLIENT_ID** and **QB_CLIENT_SECRET** you just got.
4.  Set `QB_ENVIRONMENT="production"`.

---

## **Part 2: Get Your Access Tokens (Run This Once)**

Now we will run the `get_oauth_tokens.py` script to get your permanent tokens.

1.  **Install dependencies:**
    ```sh
    pip install -r requirements.txt
    ```
2.  **Run the token script:**
    ```sh
    python get_oauth_tokens.py
    ```
3.  **Follow the instructions:**
    * The script will start a temporary web server on `localhost:8000`.
    * It will print a long URL. Copy and paste this URL into your web browser.
    * QuickBooks will ask you to log in and authorize your app.
    * After you click "Connect", you will be redirected to a `localhost:8000` page. The page will say "Success!"
    * Go back to your terminal. The script will have automatically detected the connection.
    * It will print your `QB_ACCESS_TOKEN`, `QB_REFRESH_TOKEN`, and `QB_REALM_ID`.
4.  **Update your `.env` file:**
    * Copy and paste these three new values into your `.env` file.

You are now fully authenticated! The main import script will use these tokens and automatically refresh them.

---

## **Part 3: Run the Importer**

1.  **Create a 'logs' directory:**
    ```sh
    mkdir logs
    ```
2.  **Run a Test Import (HIGHLY RECOMMENDED):**
    This will import only the first 5 invoices it finds in your date range.
    ```sh
    python import_script.py --limit 5
    ```
3.  **Check your database** and the `logs/import.log` file. Verify the 5 records imported correctly.
4.  **Run the Full Import:**
    Once you are confident, run the full import.
    ```sh
    python import_script.py
    ```
5.  The script will process all invoices, skipping those without LPOs and those already in your database.