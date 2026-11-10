import os


os.environ.update(
    {
        "APP_URL": "http://localhost:8000",
        "SESSION_SECRET": "pytest-session-secret",
        "PAYPAL_CLIENT_ID": "pytest-paypal-client-id",
        "PAYPAL_SECRET": "pytest-paypal-secret",
        "PAYPAL_WEBHOOK_ID": "pytest-paypal-webhook-id",
        "SUPABASE_URL": "https://pytest.supabase.invalid",
        "SUPABASE_SECRET_KEY": "pytest-supabase-secret-key",
    }
)
