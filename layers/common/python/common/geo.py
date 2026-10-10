"""Small flat-earth geometry helpers. Accurate enough for ~500 km air-parcel paths."""
import math

EARTH_RADIUS_KM = 6371.0
KM_PER_DEG_LAT = 111.32


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def travel_bearing(wind_from_deg):
    """Meteorological wind direction is where the wind comes FROM; smoke travels the opposite way."""
    return (wind_from_deg + 180.0) % 360.0


def advance(lat, lon, bearing_deg, dist_km):
    """Move dist_km along bearing_deg (0 = north, 90 = east)."""
    b = math.radians(bearing_deg)
    dlat = dist_km * math.cos(b) / KM_PER_DEG_LAT
    dlon = dist_km * math.sin(b) / (KM_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    return lat + dlat, lon + dlon
