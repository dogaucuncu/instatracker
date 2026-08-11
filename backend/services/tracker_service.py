import logging
import time
import random
from datetime import datetime, timedelta

from instagrapi.exceptions import (
    ClientThrottledError,
    FeedbackRequired,
    PleaseWaitFewMinutes,
    RateLimitError,
)

import database as db
from services import instagram_service as ig
from config import (
    INTER_FETCH_MIN_DELAY,
    INTER_FETCH_MAX_DELAY,
    MIN_SCAN_INTERVAL_MINUTES,
)

logger = logging.getLogger(__name__)


class ScanTooSoon(Exception):
    """Raised when the previous scan is too recent to safely run another."""


class EmptyFetch(Exception):
    """Raised when Instagram returns an empty list that used to have entries."""


def check_scan_allowed() -> None:
    """Refuse to enumerate the whole account again right after the last time.

    Instagram's "Daha Sonra Tekrar Dene" restriction is driven by how often an
    account performs an action, not by how many followers it has. Two full
    follower+following enumerations minutes apart is the shape it looks for.
    """
    if not MIN_SCAN_INTERVAL_MINUTES:
        return

    last = db.get_last_scan_time()
    if not last:
        return
    try:
        previous = datetime.fromisoformat(last)
    except ValueError:
        return

    earliest = previous + timedelta(minutes=MIN_SCAN_INTERVAL_MINUTES)
    remaining = earliest - datetime.utcnow()
    if remaining.total_seconds() > 0:
        minutes = max(1, round(remaining.total_seconds() / 60))
        raise ScanTooSoon(
            f"Instagram'ın hesabı kısıtlamaması için taramalar arasında en az "
            f"{MIN_SCAN_INTERVAL_MINUTES} dakika bekleniyor. "
            f"Yaklaşık {minutes} dakika sonra tekrar deneyin."
        )


def _reject_empty_fetch(label: str, fetched: list, previous_loader) -> None:
    """Abort the scan when a list came back empty but was not empty before.

    An account really can follow nobody, so an empty list is only suspicious
    when the previous snapshot had entries.
    """
    if fetched:
        return
    if not previous_loader():
        return
    raise EmptyFetch(
        f"Instagram {label} listesini boş döndürdü. Bu genellikle geçici bir "
        f"kısıtlama işaretidir; hiçbir veri kaydedilmedi. Lütfen daha sonra "
        f"tekrar deneyin."
    )


def run_scan() -> dict:
    """
    Full scan:
    1. Fetch current followers + following
    2. Save snapshots
    3. Compare with previous follower snapshot
    4. Categorize lost users (unfollowed / blocked / deactivated)
    5. Cross-check with following list → still_following flag
    6. Detect new followers
    7. Persist events
    Returns a summary dict.
    """
    # Enforced here rather than only at the call sites, so no entry point can
    # start a full enumeration without passing the rate guard.
    check_scan_allowed()

    scan_id = db.create_scan()
    events_created = 0

    try:
        # ── 1. Fetch from Instagram ────────────────────────────────────────
        # Land on the feed first so the follower list is not the opening
        # request of the session.
        ig.open_app()

        logger.info("[Scan %d] Fetching followers...", scan_id)
        current_followers = ig.get_followers()

        # Pause between the two bulk enumerations so they don't read as one
        # back-to-back scraping burst.
        pause = random.uniform(INTER_FETCH_MIN_DELAY, INTER_FETCH_MAX_DELAY)
        logger.info("[Scan %d] Pausing %.1fs before fetching following...", scan_id, pause)
        time.sleep(pause)

        logger.info("[Scan %d] Fetching following...", scan_id)
        current_following = ig.get_following()

        # Build lookup sets
        current_follower_pks = {u["pk"] for u in current_followers}
        current_following_pks = {u["pk"] for u in current_following}

        # ── 2. Load previous snapshot for comparison ───────────────────────
        is_first_scan = db.get_snapshot_count() == 0
        previous_followers = db.get_latest_follower_snapshot_users()  # Before saving new one

        # ── 2b. Reject a fetch that came back suspiciously empty ───────────
        # A soft-blocked account gets HTTP 200 with an empty user array rather
        # than an error. Trusting that would be destructive: an empty follower
        # list makes *every* existing follower look like they unfollowed, and an
        # empty following list would clear every "Hala Takip Ediyorsunuz" flag.
        _reject_empty_fetch("takipçi", current_followers, db.get_latest_follower_snapshot_users)
        _reject_empty_fetch("takip edilen", current_following, db.get_latest_following_snapshot_users)

        # ── 3. Save new snapshots ──────────────────────────────────────────
        db.save_follower_snapshot(scan_id, current_followers)
        db.save_following_snapshot(scan_id, current_following)

        # ── 3b. Re-derive still_following for every past event ─────────────
        # Step 5 below only touches people who left the follower list during
        # *this* scan, so an old event would otherwise keep its original flag
        # forever.
        changed = db.sync_still_following(current_following_pks)
        if changed:
            logger.info(
                "[Scan %d] Refreshed still_following on %d event(s)", scan_id, changed
            )

        if is_first_scan:
            logger.info("[Scan %d] First scan — baseline created, no comparison possible yet.", scan_id)
            db.complete_scan(scan_id, 0, 0)
            return {
                "scan_id": scan_id,
                "status": "first_scan",
                "new_followers": 0,
                "lost_followers": 0,
                "events_created": 0,
                "message": "İlk tarama tamamlandı! Takipçi listesi kaydedildi. Bir sonraki taramada değişiklikler tespit edilecek.",
            }

        # ── 4. Detect changes ──────────────────────────────────────────────
        previous_follower_pks = {u.get("pk") or u.get("user_pk") for u in previous_followers}
        previous_follower_map = {u.get("pk") or u.get("user_pk"): u for u in previous_followers}
        current_follower_map = {u["pk"]: u for u in current_followers}

        lost_pks = previous_follower_pks - current_follower_pks
        new_pks = current_follower_pks - previous_follower_pks

        logger.info("[Scan %d] Lost: %d | New: %d", scan_id, len(lost_pks), len(new_pks))

        # ── 5. Process lost followers ──────────────────────────────────────
        for pk in lost_pks:
            user = previous_follower_map[pk]
            username = user["username"]
            full_name = user.get("full_name", "")
            profile_pic_url = user.get("profile_pic_url")

            # Determine why they're gone
            status = ig.check_user_status(pk, username)

            if status == "deactivated":
                event_type = "deactivated"
            elif status == "blocked":
                event_type = "blocked"
            else:
                event_type = "unfollowed"

            # Cross-check: do I still follow them?
            still_following = pk in current_following_pks

            # Save event (skip if identical event was already recorded today)
            if not db.event_exists_today(pk, event_type):
                db.save_event(
                    user_pk=pk,
                    username=username,
                    full_name=full_name,
                    profile_pic_url=profile_pic_url,
                    event_type=event_type,
                    still_following=still_following,
                    details={"status_check": status},
                )
                events_created += 1
                logger.info(
                    "[Scan %d] [%s] @%s | still_following=%s",
                    scan_id, event_type.upper(), username, still_following
                )
            # No `else` branch: an event recorded earlier today already had its
            # flag refreshed by the full sync in step 3b.

        # ── 6. Process new followers ───────────────────────────────────────
        for pk in new_pks:
            user = current_follower_map[pk]
            username = user["username"]
            full_name = user.get("full_name", "")
            profile_pic_url = user.get("profile_pic_url")

            if not db.event_exists_today(pk, "new_follower"):
                db.save_event(
                    user_pk=pk,
                    username=username,
                    full_name=full_name,
                    profile_pic_url=profile_pic_url,
                    event_type="new_follower",
                    still_following=pk in current_following_pks,
                )
                events_created += 1

        # ── 7. Complete scan ───────────────────────────────────────────────
        db.complete_scan(scan_id, len(new_pks), len(lost_pks))

        return {
            "scan_id": scan_id,
            "status": "completed",
            "new_followers": len(new_pks),
            "lost_followers": len(lost_pks),
            "events_created": events_created,
            "message": f"Tarama tamamlandı! {len(lost_pks)} kişi takipten çıktı, {len(new_pks)} yeni takipçi var.",
        }

    except (PleaseWaitFewMinutes, ClientThrottledError, RateLimitError, FeedbackRequired) as e:
        # Instagram asked us to stop. Say so plainly instead of letting the
        # user hit "Tara" again, which is what turns a short throttle into a
        # multi-day restriction.
        logger.warning("[Scan %d] Throttled by Instagram: %s", scan_id, e)
        user_msg = (
            "Instagram şu an bu hesaptan çok sık işlem yapıldığını düşünüyor ve "
            "istekleri geçici olarak sınırlıyor. Birkaç saat (gerekirse 24 saat) "
            "hiç tarama yapmadan bekleyin; bu sürede telefondan normal şekilde "
            "Instagram kullanmanız kısıtlamanın daha hızlı kalkmasına yardımcı olur."
        )
        db.fail_scan(scan_id, user_msg)
        raise RuntimeError(user_msg) from e

    except Exception as e:
        err_str = str(e)
        logger.error("[Scan %d] Error: %s", scan_id, err_str, exc_info=True)
        if "expecting value" in err_str.lower() or "challenge" in err_str.lower():
            user_msg = "Instagram güvenlik doğrulaması istiyor. Lütfen telefondan Instagram'a girip 'Bendim' diyerek onaylayın ve tekrar deneyin."
        else:
            user_msg = err_str
        db.fail_scan(scan_id, user_msg)
        raise
