"""Cities we issue forecasts for, plus the source-region and wind-grid extents."""

CITIES = {
    "delhi": {"name": "Delhi", "name_hi": "दिल्ली", "lat": 28.6139, "lon": 77.2090},
    "gurugram": {"name": "Gurugram", "name_hi": "गुरुग्राम", "lat": 28.4595, "lon": 77.0266},
    "chandigarh": {"name": "Chandigarh", "name_hi": "चंडीगढ़", "lat": 30.7333, "lon": 76.7794},
    "ludhiana": {"name": "Ludhiana", "name_hi": "लुधियाना", "lat": 30.9010, "lon": 75.8573},
    "jaipur": {"name": "Jaipur", "name_hi": "जयपुर", "lat": 26.9124, "lon": 75.7873},
}

# Cities where the stagnation (air-mixing) label has been checked against measured PM2.5 on held-out seasons (2017-2019).
# Jaipur showed no relationship; Chandigarh and Ludhiana lack usable data. Others get the label marked "indicative".
STAGNATION_VALIDATED = {"delhi", "gurugram"}

# west, south, east, north - where we look for crop-residue fires (Punjab / Haryana / N. Rajasthan / W. UP)
FIRE_BBOX = (73.5, 27.5, 78.5, 32.5)

# Coarse wind grid covering fire region + all cities. One Open-Meteo call fetches all points.
GRID_LATS = [26.0, 27.5, 29.0, 30.5, 32.0, 33.5]
GRID_LONS = [73.0, 74.5, 76.0, 77.5, 79.0]


# Urban cores where satellite fire detections are mostly waste, industrial and cooking-fuel burning, not crop residue.
# (name, lat, lon, radius_km). Approximate centres; radii are deliberately modest so outskirts farmland still counts
# (e.g. Delhi's Narela/Bawana belt is ~30 km from the centre and stays in).
URBAN_EXCLUSIONS = [
    ("Delhi", 28.6139, 77.2090, 18), ("Noida", 28.5355, 77.3910, 8), ("Ghaziabad", 28.6692, 77.4538, 8),
    ("Gurugram", 28.4595, 77.0266, 10), ("Faridabad", 28.4089, 77.3178, 8), ("Sonipat", 28.9931, 77.0151, 5),
    ("Panipat", 29.3909, 76.9635, 6), ("Rohtak", 28.8955, 76.6066, 6), ("Karnal", 29.6857, 76.9905, 5),
    ("Ambala", 30.3782, 76.7767, 6), ("Chandigarh", 30.7333, 76.7794, 8), ("Mohali", 30.7046, 76.7179, 5),
    ("Panchkula", 30.6942, 76.8606, 5), ("Ludhiana", 30.9010, 75.8573, 12), ("Jalandhar", 31.3260, 75.5762, 8),
    ("Amritsar", 31.6340, 74.8723, 10), ("Patiala", 30.3398, 76.3869, 7), ("Bathinda", 30.2110, 74.9455, 6),
    ("Hisar", 29.1492, 75.7217, 6), ("Meerut", 28.9845, 77.7064, 8), ("Jaipur", 26.9124, 75.7873, 15),
]


def grid_points():
    return [(la, lo) for la in GRID_LATS for lo in GRID_LONS]
