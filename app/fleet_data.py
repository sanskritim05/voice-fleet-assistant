"""Mock fleet records for the agent's lookup tools.

A real deployment would call the fleet's telematics and maintenance systems.
"""

TRUCKS = {
    "truck-8821": {
        "location": "I-80 eastbound, mile 212 near Des Moines, IA",
        "service_history": [
            {"date": "2026-08-19", "work": "Brake pads and rotors replaced, rear axle"},
            {"date": "2026-06-02", "work": "Oil change, coolant flush"},
            {"date": "2026-03-11", "work": "Steer tires replaced"},
        ],
        "open_recalls": [],
    },
    "truck-4417": {
        "location": "I-70 westbound, mile 88 near Columbia, MO",
        "service_history": [
            {"date": "2026-07-30", "work": "Air dryer cartridge replaced"},
            {"date": "2026-05-14", "work": "Alternator replaced"},
        ],
        "open_recalls": ["Brake chamber inspection bulletin, issued 2026-08"],
    },
}

DEFAULT_TRUCK = {
    "location": "Unknown, last GPS ping over 1 hour ago",
    "service_history": [],
    "open_recalls": [],
}

REPAIR_SHOPS = [
    {"name": "Midwest Truck & Trailer", "distance_miles": 8, "exit": "Exit 214", "services": ["brake", "tire", "engine", "electrical"], "open_24h": True},
    {"name": "Love's Truck Care", "distance_miles": 14, "exit": "Exit 220", "services": ["tire", "electrical", "general"], "open_24h": True},
    {"name": "Hawkeye Diesel Repair", "distance_miles": 23, "exit": "Exit 231", "services": ["engine", "brake"], "open_24h": False},
]


def truck_record(truck_id: str) -> dict:
    return TRUCKS.get(truck_id, DEFAULT_TRUCK)


def nearest_shop(service: str) -> dict | None:
    matches = [shop for shop in REPAIR_SHOPS if service in shop["services"]] or REPAIR_SHOPS
    return min(matches, key=lambda shop: shop["distance_miles"])
