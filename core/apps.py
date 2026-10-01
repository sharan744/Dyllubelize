import os
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # Start the in-process expiry scheduler only when explicitly enabled,
        # and only in the main runserver process (not the autoreload watcher).
        if os.environ.get("RUN_SCHEDULER") not in ("1", "true", "True"):
            return
        if os.environ.get("RUN_MAIN") == "false":
            return
        try:
            from core import scheduler
            scheduler.start()
        except Exception:
            pass
