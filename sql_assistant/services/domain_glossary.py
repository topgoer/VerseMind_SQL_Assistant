DOMAIN_GLOSSARY = {
    "SOH (State of Health)": {
        "meaning": "Snapshot of the battery's long-term condition: the percentage of its original usable capacity that remains. 100% when new, trending downward as the battery ages and degrades.",
        "why_it_matters": "Most queries revolve around SOH thresholds (e.g., 'vehicles < 30 %')."
    },
    "SOC (State of Charge)": {
        "meaning": "Battery 'fuel-gauge' expressed as a percentage (0% = empty, 100% = full).",
        "why_it_matters": "Most queries revolve around SOC thresholds (e.g., 'vehicles < 30 %')."
    },
    "SOC comfort zone": {
        "meaning": "The SOC band a fleet considers 'healthy' for daily ops—typically 30–80 %. Operating outside this band too often accelerates battery ageing.",
        "why_it_matters": "In the dataset, you'll see derived metrics such as the average SOC comfort zone and the boolean overcharging flag (time spent > 90 % SOC)."
    },
    "SRM T3": {
        "meaning": "A light-duty electric van: SRM is the make (manufacturer), T3 is the model. Comparable to 'Hyundai Ioniq' → make Hyundai, model Ioniq.",
        "why_it_matters": "Table vehicles.model = 'SRM T3' is frequently filtered in the sample queries."
    },
    "GBM6296G": {
        "meaning": "A Singapore vehicle registration plate (license-plate number). Plate numbers uniquely identify vehicles in human-facing questions, while vin and vehicle_id do so in the database.",
        "why_it_matters": ""
    },
    "VIN": {
        "meaning": "Vehicle Identification Number—17-char unique ID issued by OEM.",
        "why_it_matters": "Used as a secondary key and for cross-referencing external systems."
    },
    "Trip": {
        "meaning": "A continuous vehicle movement episode from start_ts to end_ts (table trips). Contains distance, energy, idle minutes.",
        "why_it_matters": ""
    },
    "Charging session": {
        "meaning": "Period when the vehicle is plugged in (table charging_sessions). Contains start/end SOC and energy delivered.",
        "why_it_matters": ""
    },
    "Alert": {
        "meaning": "Event that breaches a safety or performance threshold (e.g. HighTemp, Overcharge, LowSOC). Logged in table alerts.",
        "why_it_matters": ""
    },
    "Battery cycle": {
        "meaning": "One charging-and-discharging cycle tracked for long-term State-of-Health (SOH) analysis.",
        "why_it_matters": ""
    },
    "Geofence event": {
        "meaning": "Entry/exit of a predefined geographic area (e.g. Depot, Airport).",
        "why_it_matters": ""
    },
    "Fleet/Vehicle/Driver hierarchy": {
        "meaning": "fleets → vehicles → trips / alerts / telemetry, and drivers link to trips through driver_trip_map. All natural language (NL) queries should respect this hierarchy.",
        "why_it_matters": ""
    }
} 