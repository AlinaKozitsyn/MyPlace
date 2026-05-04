import os

import requests


def normalize_location(location: str) -> str:
    normalized = location.strip()
    lowered = normalized.lower()
    if "israel" in lowered or "ישראל" in normalized:
        return normalized

    return f"{normalized}, Israel"


def get_google_mode(commute_mode: str) -> str:
    if commute_mode == "public_transport":
        return "transit"

    return "driving"


def get_commute(
    origin: str,
    destination: str,
    commute_mode: str,
    departure_time: int | None = None,
) -> dict:
    """
    departure_time: Unix timestamp (seconds). If provided, Google may return duration_in_traffic.
    The returned duration is the longer of duration and duration_in_traffic.
    """
    google_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not google_api_key:
        return {
            "status": "NO_API_KEY",
            "duration_min": None,
            "distance_km": None,
        }

    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    google_mode = get_google_mode(commute_mode)
    params = {
        "origins": normalize_location(origin),
        "destinations": normalize_location(destination),
        "mode": google_mode,
        "key": google_api_key,
        "language": "he",
        "region": "il",
    }

    if departure_time is not None:
        params["departure_time"] = int(departure_time)
        if google_mode == "driving":
            params["traffic_model"] = "best_guess"

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        top_status = data.get("status")
        top_error = data.get("error_message")
        rows = data.get("rows") or []
        elements = rows[0].get("elements") if rows else []
        element = elements[0] if elements else None

        print("[GOOGLE RAW] top-level status:", top_status)
        print("[GOOGLE RAW] error_message:", top_error)
        print("[GOOGLE RAW] rows_count:", len(rows))
        print("[GOOGLE RAW] element:", element)

        if top_status != "OK":
            return {
                "status": top_status or "API_ERROR",
                "duration_min": None,
                "distance_km": None,
                "error": top_error or "Google Distance Matrix returned a non-OK top-level status",
            }

        if not element:
            return {
                "status": "NO_ELEMENT",
                "duration_min": None,
                "distance_km": None,
                "error": "Google Distance Matrix returned no route element",
            }

        if element.get("status") != "OK":
            return {
                "status": element.get("status", "ERROR"),
                "duration_min": None,
                "distance_km": None,
                "error": element.get("error_message"),
            }

        duration = element.get("duration") or {}
        distance = element.get("distance") or {}
        traffic_duration = element.get("duration_in_traffic") or {}

        duration_value = duration.get("value")
        distance_value = distance.get("value")
        traffic_value = traffic_duration.get("value")

        longest_duration_value = None
        if duration_value is not None and traffic_value is not None:
            longest_duration_value = max(duration_value, traffic_value)
        elif duration_value is not None:
            longest_duration_value = duration_value
        else:
            longest_duration_value = traffic_value

        duration_min = round(longest_duration_value / 60) if longest_duration_value is not None else None
        distance_km = round(distance_value / 1000, 1) if distance_value is not None else None

        return {
            "status": "OK",
            "duration_min": duration_min,
            "distance_km": distance_km,
        }

    except Exception as e:
        return {
            "status": "REQUEST_FAILED",
            "duration_min": None,
            "distance_km": None,
            "error": str(e)[:200],
        }


def get_drive_commute(origin: str, destination: str, departure_time: int | None = None) -> dict:
    return get_commute(
        origin=origin,
        destination=destination,
        commute_mode="private_car",
        departure_time=departure_time,
    )
