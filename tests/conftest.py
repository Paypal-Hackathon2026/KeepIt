import os


os.environ.update(
    {
        "APP_URL": "http://localhost:8000",
        "SESSION_SECRET": "test-session-secret",
        "PAYPAL_CLIENT_ID": "test-paypal-client-id",
        "PAYPAL_SECRET": "test-paypal-secret",
        "PAYPAL_WEBHOOK_ID": "test-paypal-webhook-id",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SECRET_KEY": "test-supabase-secret-key",
    }
)
