"""
Run a dedicated blocking scheduler process that emails the expiry alert daily.
Use this if you prefer a separate process over the in-process scheduler:

    python manage.py run_scheduler

Set EXPIRY_CHECK_HOUR to change the time (default 08:00).
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run a blocking APScheduler that emails expiry alerts once a day."

    def handle(self, *args, **opts):
        from core import scheduler
        sched = scheduler.start(blocking=True)
        if sched is None:
            self.stderr.write("Could not start scheduler (is APScheduler installed?).")
            return
        self.stdout.write(self.style.SUCCESS("Scheduler running. Press Ctrl+C to stop."))
        try:
            import time
            while True:
                time.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            sched.shutdown()
