import logging
import time
import random
import database as db
from services import instagram_service as ig
from config import INTER_FETCH_MIN_DELAY, INTER_FETCH_MAX_DELAY

logger = logging.getLogger(__name__)


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
    scan_id = db.create_scan()
    events_created = 0

    try:
        # ── 1. Fetch from Instagram ────────────────────────────────────────
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

        # ── 3. Save new snapshots ──────────────────────────────────────────
        db.save_follower_snapshot(scan_id, current_followers)
        db.save_following_snapshot(scan_id, current_following)

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
            else:
                # Update still_following in case they re-followed or we unfollowed them
                db.update_event_still_following(pk, still_following)

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

    except Exception as e:
        err_str = str(e)
        logger.error("[Scan %d] Error: %s", scan_id, err_str, exc_info=True)
        if "expecting value" in err_str.lower() or "challenge" in err_str.lower():
            user_msg = "Instagram güvenlik doğrulaması istiyor. Lütfen telefondan Instagram'a girip 'Bendim' diyerek onaylayın ve tekrar deneyin."
        else:
            user_msg = err_str
        db.fail_scan(scan_id, user_msg)
        raise
