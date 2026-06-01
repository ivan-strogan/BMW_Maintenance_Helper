"""
Parse a BMW maintenance schedule PDF into config/schedule.yaml.

Designed for the community N54 schedule format (Version 1.1b) but the
interval-extraction logic works on any schedule that states intervals in
prose: "Replace every 12,000", "Inspect every 24,000", etc.
"""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber
from ruamel.yaml import YAML

# Known item display names -> stable IDs used in schedule.yaml.
# Add entries here when supporting new schedules.
_ITEM_IDS: dict[str, str] = {
    "Oil & Filter Change":               "oil_filter",
    "Tires":                             "tires",
    "Battery":                           "battery",
    "Wheel Alignment":                   "wheel_alignment",
    "Brake Fluid":                       "brake_fluid",
    "Manual Transmission Clutch Fluid":  "clutch_fluid",
    "Interior Air Filter":               "interior_air_filter",
    "Engine Air Filter":                 "engine_air_filter",
    "Change Engine Coolant":             "engine_coolant",
    "Power Steering Fluid":              "power_steering_fluid",
    "Manual Transmission Gearbox Oil":   "gearbox_oil",
    "Differential Oil":                  "differential_oil",
    "Spark Plugs":                       "spark_plugs",
    "Fuel Filter":                       "fuel_filter",
    "Engine Drive Belts":                "drive_belts",
    "Oxygen Sensors":                    "oxygen_sensors",
    "Water and Fuel Hoses":              "water_fuel_hoses",
}

# Catalog hints for the RealOEM browser (added later; empty here).
_CATALOG_HINTS: dict[str, str] = {
    "oil_filter":         "Engine > Lubrication System > Oil Filter",
    "interior_air_filter":"Heating / Air Conditioning > Microfilter",
    "engine_air_filter":  "Engine > Air Supply > Air Filter",
    "brake_fluid":        "Brakes > Brake Fluid",
    "clutch_fluid":       "Clutch > Clutch Hydraulics",
    "engine_coolant":     "Engine > Cooling System",
    "power_steering_fluid":"Steering > Power Steering",
    "gearbox_oil":        "Manual Transmission",
    "differential_oil":   "Rear Axle > Differential",
    "spark_plugs":        "Engine > Ignition System > Spark Plugs",
    "drive_belts":        "Engine > Belt Drive",
    "oxygen_sensors":     "Engine > Exhaust System",
    "water_fuel_hoses":   "Engine > Cooling System > Hoses",
    "fuel_filter":        "Fuel Preparation System > Fuel Filter",
}


def _parse_km(text: str) -> int | None:
    """Extract the first integer from strings like '12,000' or '48000'."""
    m = re.search(r"([\d,]+)", text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_months(text: str) -> int | None:
    """Extract months from strings like '2 years', '2.5 years', '1 year'."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*years?", text, re.I)
    if not m:
        return None
    years = float(m.group(1))
    return round(years * 12)


def _extract_intervals(prose: str) -> dict:
    """
    Parse interval fields from the description text beneath an item name.

    Returns a dict with keys: interval_replace_km, interval_inspect_km,
    interval_replace_months, interval_inspect_months,
    bmw_recommendation_km, bmw_recommendation_months, notes.
    """
    result: dict[str, int | str | None] = {
        "interval_replace_km":    None,
        "interval_inspect_km":    None,
        "interval_replace_months":None,
        "interval_inspect_months":None,
        "bmw_recommendation_km":  None,
        "bmw_recommendation_months": None,
        "notes": prose.strip() or None,
    }
    lower = prose.lower()

    # --- replace km ---
    for pat in [
        r"replace every ([\d,]+)",
        r"change every ([\d,]+)",
    ]:
        m = re.search(pat, lower)
        if m:
            result["interval_replace_km"] = _parse_km(m.group(1))
            break

    # --- inspect km ---
    m = re.search(r"inspect(?:\s+\w+)*?\s+every ([\d,]+)", lower)
    if m:
        result["interval_inspect_km"] = _parse_km(m.group(1))

    # Combined "inspect every X, replace every Y"
    m = re.search(r"inspect every ([\d,]+),?\s+replace(?:\s+every)?\s+([\d,]+)", lower)
    if m:
        result["interval_inspect_km"] = _parse_km(m.group(1))
        result["interval_replace_km"] = _parse_km(m.group(2))

    # --- replace / inspect months ("or every 2.5 years") ---
    # Look for "replace every X or every Y years"
    m = re.search(r"replace every [\d,]+ or every (\d+(?:\.\d+)?\s*years?)", lower)
    if m:
        result["interval_replace_months"] = _parse_months(m.group(1))
    # "inspect every X or every year"
    m = re.search(r"inspect every [\d,]+ or every (\d+(?:\.\d+)?\s*years?)", lower)
    if m:
        result["interval_inspect_months"] = _parse_months(m.group(1))

    # --- BMW recommendation km ---
    for pat in [
        r"bmw recommends(?:\s+every)?\s+([\d,]+)",
        r"bmw recommendation.*?([\d,]+)",
    ]:
        m = re.search(pat, lower)
        if m and _parse_km(m.group(1)):
            result["bmw_recommendation_km"] = _parse_km(m.group(1))
            break

    # --- BMW recommendation months ---
    m = re.search(r"bmw recommends every (\d+(?:\.\d+)?\s*years?)", lower)
    if m:
        result["bmw_recommendation_months"] = _parse_months(m.group(1))

    return result


def _extract_full_text(pdf_path: Path) -> str:
    """Return all words from every page joined by spaces."""
    parts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            parts.append(" ".join(w["text"] for w in words))
    return " ".join(parts)


def _split_items(full_text: str) -> list[tuple[str, str]]:
    """
    Split the full page text into (display_name, prose_description) pairs
    by locating known item names as anchors.

    Returns items in document order.
    """
    # Build a regex that matches any known item name
    anchors = sorted(_ITEM_IDS.keys(), key=len, reverse=True)  # longest first
    pattern = "(" + "|".join(re.escape(a) for a in anchors) + ")"
    parts = re.split(pattern, full_text)

    items: list[tuple[str, str]] = []
    i = 1
    while i < len(parts):
        name = parts[i].strip()
        prose = parts[i + 1].strip() if i + 1 < len(parts) else ""
        # Strip trailing R/I markers and KM numbers from prose
        prose = re.sub(r"\b[RI]\b", " ", prose)
        prose = re.sub(r"\s+", " ", prose).strip()
        items.append((name, prose))
        i += 2

    return items


def parse_schedule_pdf(pdf_path: Path) -> list[dict]:
    """
    Parse a maintenance schedule PDF and return a list of schedule item dicts
    ready to be written to schedule.yaml.
    """
    full_text = _extract_full_text(pdf_path)
    raw_items = _split_items(full_text)

    result: list[dict] = []
    for display_name, prose in raw_items:
        item_id = _ITEM_IDS.get(display_name)
        if not item_id:
            continue  # unknown item name -- skip silently
        intervals = _extract_intervals(prose)
        result.append({
            "id":   item_id,
            "name": display_name if display_name != "Change Engine Coolant" else "Engine Coolant",
            **intervals,
            "catalog_hint": _CATALOG_HINTS.get(item_id),
        })

    return result


def write_schedule_yaml(items: list[dict], out_path: Path, source_file: str = "") -> None:
    """Write parsed items to a schedule.yaml file."""
    y = YAML()
    y.default_flow_style = False

    # Build the full schedule structure
    data = {
        "source":  source_file,
        "engine":  "N54",
        "unit":    "km",
        "version": "",
        "items":   items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        y.dump(data, f)


def import_schedule(pdf_path: Path, out_path: Path) -> list[dict]:
    """Parse PDF and write schedule.yaml. Returns the parsed items."""
    items = parse_schedule_pdf(pdf_path)
    write_schedule_yaml(items, out_path, source_file=pdf_path.name)
    return items
