"""
Background scheduler (APScheduler) that emails an expiry alert once a day.

It runs *inside* the web process, so nothing extra needs to stay open. It is
off by default; switch it on with an environment variable:

    RUN_SCHEDULER=1            # enable the in-process daily job
    EXPIRY_CHECK_HOUR=8        # optional, hour of day (0-23), default 8

Alternatives if you'd rather not run it in-process:
    python manage.py check_expiry           # run once (e.g. from Task Scheduler / cron)
    python manage.py run_scheduler          # run a dedicated blocking scheduler process
"""
import os
import logging

log = logging.getLogger(__name__)
_started = False


def _run_check():
    try:
        from django.core.management import call_command
        call_command("check_expiry")
    except Exception as exc:  # never let the job crash the scheduler
        log.warning("Expiry check failed: %s", exc)


def start(blocking=False):
    """Start the daily expiry-check job. Returns the scheduler, or None."""
    global _started
    if _started and not blocking:
        return None
    try:
        if blocking:
            from apscheduler.schedulers.blocking import BlockingScheduler as S
        else:
            from apscheduler.schedulers.background import BackgroundScheduler as S
        from apscheduler.triggers.cron import CronTrigger
    except Exception:
        log.warning("APScheduler not installed — run `pip install APScheduler` "
                    "or call `manage.py check_expiry` from cron instead.")
        return None

    hour = int(os.environ.get("EXPIRY_CHECK_HOUR", "8"))
    tzname = os.environ.get("EXPIRY_TZ", "Asia/Kolkata")
    tz = None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tzname)
    except Exception:
        tz = None
    try:
        sched = S(timezone=tz) if tz else S()
    except Exception:
        # last-resort: UTC, so a bad local TZ never blocks startup
        from datetime import timezone as _tz
        sched = S(timezone=_tz.utc)
    trigger = CronTrigger(hour=hour, minute=0, timezone=tz) if tz else CronTrigger(hour=hour, minute=0)
    sched.add_job(_run_check, trigger,
                  id="expiry_check", replace_existing=True,
                  misfire_grace_time=3600)
    sched.start()
    _started = True
    log.info("Expiry scheduler started (daily at %02d:00).", hour)
    return sched
