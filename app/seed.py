"""Populate the incident log with realistic demo data.

Usage: python -m app.seed [--reset]
"""

import argparse
from datetime import datetime, timedelta, timezone

from app.agent import fallback_rule_response
from app.storage import clear_issues, save_issue

DEMO_REPORTS = [
    # (minutes ago, driver, truck, transcript, status)
    (6, "driver-ana-r", "truck-4417", "My brakes are making a grinding noise when I slow down.", "open"),
    (19, "driver-marcus-t", "truck-2290", "Tire pressure light just came on, rear left.", "acknowledged"),
    (34, "driver-lee-k", "truck-8821", "Tell dispatch I'm running about forty minutes late because of traffic on I-80.", "open"),
    (52, "driver-priya-s", "truck-3105", "Engine temperature is climbing and I can smell coolant.", "open"),
    (75, "driver-dan-w", "truck-5562", "Check engine light is on but the truck feels normal.", "acknowledged"),
    (98, "driver-ana-r", "truck-4417", "Left headlight is out.", "resolved"),
    (130, "driver-jo-m", "truck-7730", "Battery warning light keeps flickering.", "open"),
    (165, "driver-marcus-t", "truck-2290", "Customer asked to push delivery to tomorrow morning, please notify dispatch.", "resolved"),
    (210, "driver-sam-b", "truck-6048", "There's smoke coming from under the hood.", "resolved"),
    (260, "driver-lee-k", "truck-8821", "Hearing a vibration in the steering wheel above sixty.", "acknowledged"),
    (320, "driver-priya-s", "truck-3105", "Small oil leak spotted at the fuel stop, monitoring it.", "resolved"),
    (400, "driver-dan-w", "truck-5562", "Passenger side wiper is streaking.", "open"),
]


def seed(reset: bool = False) -> int:
    if reset:
        clear_issues()

    now = datetime.now(timezone.utc)
    for minutes_ago, driver_id, truck_id, transcript, status in DEMO_REPORTS:
        result = fallback_rule_response(transcript)
        save_issue(
            transcript=transcript,
            driver_id=driver_id,
            truck_id=truck_id,
            category=result["category"],
            severity=result["severity"],
            decision=result["decision"],
            actions=result["actions"],
            source="rules",
            timestamp=(now - timedelta(minutes=minutes_ago)).isoformat(),
            status=status,
        )
    return len(DEMO_REPORTS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="clear the log before seeding")
    args = parser.parse_args()
    print(f"Seeded {seed(reset=args.reset)} demo incidents.")
