from common import model, sources
from common.cities import CITIES
from common.geo import advance, haversine_km, travel_bearing
from common.model import FireCell, WindField, assess_city, cluster_fires, risk_level


def test_travel_bearing_is_opposite_of_wind_from():
    assert travel_bearing(315) == 135   # NW wind blows towards the south-east
    assert travel_bearing(90) == 270


def test_advance_and_haversine_agree():
    lat, lon = advance(30.0, 76.0, 135.0, 100.0)
    assert abs(haversine_km(30.0, 76.0, lat, lon) - 100.0) < 1.0
    assert lat < 30.0 and lon > 76.0   # south-east


def test_cluster_fires_bins_and_sums_frp():
    fires = [{"lat": 30.01, "lon": 75.01, "frp": 10}, {"lat": 30.02, "lon": 75.02, "frp": 5},
             {"lat": 31.5, "lon": 75.0, "frp": 7}]
    cells = cluster_fires(fires)
    assert len(cells) == 2
    assert sorted(c.frp for c in cells) == [7, 15]
    assert sorted(c.count for c in cells) == [1, 2]


def test_parcel_reaches_city_downwind_with_expected_hour():
    # Fire 150 km north-west of Delhi, NW wind at 15 km/h: parcel enters the 50 km radius after
    # (150 - 50) / 15 = 6.7 h, so the first hour inside is 7.
    city = CITIES["delhi"]
    start = advance(city["lat"], city["lon"], 315.0, 150.0)
    cell = FireCell(start[0], start[1], frp=100.0, count=5)
    path = model.forward_trajectory(cell, sources.synthetic_wind(315.0, 15.0))
    assert model.arrival_hour(path, city["lat"], city["lon"]) == 7


def test_fire_already_inside_city_radius_counts_as_local_smoke():
    city = CITIES["ludhiana"]
    start = advance(city["lat"], city["lon"], 45.0, 30.0)   # 30 km north-east, wind blows it away
    cell = FireCell(start[0], start[1], frp=50.0, count=3)
    rec = assess_city(city, [cell], sources.synthetic_wind(315.0, 15.0))
    assert rec["arrival_hour"] == 1 and rec["fire_cells_upwind"] == 1


def test_parcel_upwind_of_fire_never_arrives():
    city = CITIES["delhi"]
    start = advance(city["lat"], city["lon"], 135.0, 150.0)   # fire south-east, wind blows further away
    cell = FireCell(start[0], start[1], frp=100.0, count=5)
    path = model.forward_trajectory(cell, sources.synthetic_wind(315.0, 15.0))
    assert model.arrival_hour(path, city["lat"], city["lon"]) is None


def test_assess_city_downwind_vs_decoy(sample_fires_csv):
    cells = cluster_fires(sources.parse_fires(sample_fires_csv))
    wind = sources.synthetic_wind(315.0, 15.0)
    delhi = assess_city(CITIES["delhi"], cells, wind)
    jaipur = assess_city(CITIES["jaipur"], cells, wind)
    assert delhi["fire_cells_upwind"] > 0 and delhi["arrival_hour"] is not None
    assert delhi["window_start_hour"] <= delhi["peak_hour"] <= delhi["window_end_hour"]
    assert delhi["smoke_load"] > jaipur["smoke_load"]
    assert all(c["arrival_hour"] <= model.HORIZON_H for c in delhi["contributors"])


def test_wind_from_the_south_clears_delhi(sample_fires_csv):
    cells = cluster_fires(sources.parse_fires(sample_fires_csv))
    rec = assess_city(CITIES["delhi"], cells, sources.synthetic_wind(180.0, 15.0))
    assert rec["risk_level"] == "LOW" and rec["arrival_hour"] is None


def test_risk_level_thresholds_and_baseline_bump():
    assert risk_level(0) == "LOW"
    assert risk_level(100) == "MODERATE"
    assert risk_level(499) == "MODERATE"
    assert risk_level(500) == "HIGH"
    assert risk_level(2000) == "SEVERE"
    assert risk_level(150, pm25_max_24h=300) == "HIGH"       # already-bad air bumps a level
    assert risk_level(0, pm25_max_24h=300) == "LOW"          # ...but only if smoke is coming
    assert risk_level(5000, pm25_max_24h=300) == "SEVERE"    # capped


def test_wind_field_clamps_hour_and_picks_nearest_point():
    wf = WindField({(28.0, 77.0): [(10, 90), (20, 90)], (31.0, 75.0): [(5, 0)]})
    assert wf.at(28.1, 77.1, 0) == (10, 90)
    assert wf.at(28.1, 77.1, 99) == (20, 90)
    assert wf.at(30.9, 75.1, 3) == (5, 0)
