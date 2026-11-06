"""Release-level integrity tests for release/v1.0.

These tests are intentionally independent of the raw PDF archive. They check the
published tables, the data dictionary, the manifest and the frozen master hashes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release" / "v1.0"
DATA = RELEASE / "data"

MASTER_HASHES = {
    "sites.csv": "bf0b5bbe6387c377f667a8001ffa2e9ced4aae85ae4bdd85f97d530d22225a51",
    "annual_observations.csv": "ec50fd5628693d16b5f979a6fd7eb3f9d39cfafd0b1f6396e6fea1549b45dcd2",
    "climate.csv": "9fc96cc8b91bfb6df71587d1859f61c9bf1b5d885c0bca5a3413740d7cb6f565",
}

EXPECTED_FILES = [
    "README.md",
    "DATASET_CARD.md",
    "DATA_DICTIONARY.csv",
    "QA_REPORT.md",
    "SOURCES.md",
    "CITATION.cff",
    "LICENSE",
    "LICENSE-DATA",
    "manifest.csv",
    "data/sites_108.csv",
    "data/lfg_measurements.csv",
    "data/waste_inflow_annual.csv",
    "data/waste_composition.csv",
    "data/climate_annual.csv",
    "data/integrated_sites_108.csv",
    "data/sites_108.geojson",
    "data/qa_validation_sample.csv",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / name, dtype=str, keep_default_na=False)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_release_files_exist():
    missing = [name for name in EXPECTED_FILES if not (RELEASE / name).is_file()]
    assert not missing, f"missing release files: {missing}"


def test_sites_count_and_unique_ids():
    sites = read("sites_108.csv")
    assert len(sites) == 108
    assert sites["landfill_id"].is_unique
    assert sites["landfill_id"].str.startswith("cdm_").all()


def test_sites_countries_and_tiers():
    sites = read("sites_108.csv")
    assert sites["iso3"].nunique() == 16
    counts = sites["evidence_tier"].value_counts().to_dict()
    assert counts == {"tier_b": 86, "tier_a": 22}
    assert sites["has_metered_lfg"].eq("True").sum() == 22
    assert sites["has_waste_inflow"].eq("True").sum() == 50
    assert sites["has_waste_composition"].eq("True").sum() == 42


def test_sites_coordinates_are_valid():
    sites = read("sites_108.csv")
    lat = pd.to_numeric(sites["latitude"], errors="coerce")
    lon = pd.to_numeric(sites["longitude"], errors="coerce")
    assert lat.notna().all() and lon.notna().all()
    assert lat.between(-90, 90).all()
    assert lon.between(-180, 180).all()
    assert (sites["latitude"] != "").all()
    assert (sites["longitude"] != "").all()


def test_lfg_rows_ids_and_sites():
    lfg = read("lfg_measurements.csv")
    assert len(lfg) == 48
    assert lfg["observation_id"].is_unique
    assert lfg["landfill_id"].nunique() == 22
    assert lfg["validation_status"].eq("found").sum() == 47
    assert lfg["validation_status"].eq("not_found").sum() == 1


def test_lfg_units_are_controlled():
    lfg = read("lfg_measurements.csv")
    assert set(lfg["lfg_volume_unit"]).issubset({"m3", "Nm3", "not_reported"})
    assert lfg["lfg_volume_unit"].eq("not_reported").sum() == 2
    assert lfg["source_url"].ne("").all()
    assert lfg["cdm_project_url"].ne("").all()
    assert lfg["observation_id"].str.match(r"^LFG-\d{4}$").all()


def test_lfg_outlier_is_flagged_and_unverified():
    lfg = read("lfg_measurements.csv")
    outlier = lfg[lfg["landfill_id"].eq("cdm_839") & lfg["lfg_total_volume"].eq("910802000.0")]
    assert len(outlier) == 1
    assert outlier.iloc[0]["qa_outlier"] == "True"
    assert outlier.iloc[0]["validation_status"] == "not_found"


def test_waste_rows_ids_and_uniqueness():
    waste = read("waste_inflow_annual.csv")
    assert len(waste) == 534
    assert waste["waste_record_id"].is_unique
    assert waste["landfill_id"].nunique() == 50
    assert not waste.duplicated(["landfill_id", "year"]).any()
    assert waste["source_url"].ne("").all()
    assert waste["waste_record_id"].str.match(r"^WST-\d{4}$").all()


def test_waste_bases_and_validation_sample():
    waste = read("waste_inflow_annual.csv")
    assert waste["inflow_basis"].value_counts().to_dict() == {
        "pdd_table": 532,
        "sipsn_2025": 2,
    }
    sampled = waste[waste["validation_status"].ne("not_sampled")]
    assert len(sampled) == 15
    assert sampled["validation_status"].eq("found").all()


def test_composition_flags_are_consistent():
    comp = read("waste_composition.csv")
    assert comp["landfill_id"].nunique() == 42
    assert len(comp) == 213
    assert comp["composition_record_id"].is_unique
    assert comp["category"].isin(
        {"food", "paper", "wood", "textile", "plastic", "glass", "metal", "other"}
    ).all()
    per_site = comp.drop_duplicates("landfill_id").set_index("landfill_id")
    for _, row in per_site.iterrows():
        total = float(row["composition_sum"])
        expected = "True" if 0.98 <= total <= 1.02 else "False"
        assert row["composition_is_complete"] == expected
    assert (per_site["composition_is_complete"] == "False").sum() == 16


def test_climate_is_complete_and_unique():
    climate = read("climate_annual.csv")
    assert len(climate) == 1728
    assert climate["landfill_id"].nunique() == 108
    assert not climate.duplicated(["landfill_id", "year"]).any()
    assert set(climate["year"]) == {str(year) for year in range(2010, 2026)}
    assert set(climate["n_months"]) == {"12"}
    for column in ["temperature_c", "humidity_pct", "precipitation_mm"]:
        values = pd.to_numeric(climate[column], errors="coerce")
        assert values.notna().all(), f"{column} has non-numeric values"


def test_integrated_table_has_one_row_per_site():
    integrated = read("integrated_sites_108.csv")
    sites = read("sites_108.csv")
    assert len(integrated) == 108
    assert integrated["landfill_id"].is_unique
    assert set(integrated["landfill_id"]) == set(sites["landfill_id"])
    assert integrated["lfg_measurement_rows"].astype(int).sum() == 48
    assert integrated["waste_inflow_rows"].astype(int).sum() == 534


def test_geojson_has_108_valid_points():
    with (DATA / "sites_108.geojson").open(encoding="utf-8") as handle:
        geojson = json.load(handle)
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 108
    ids = {feature["properties"]["landfill_id"] for feature in geojson["features"]}
    assert len(ids) == 108
    for feature in geojson["features"]:
        lon, lat = feature["geometry"]["coordinates"]
        assert -180 <= lon <= 180
        assert -90 <= lat <= 90


def test_data_dictionary_covers_every_published_column():
    dictionary = pd.read_csv(RELEASE / "DATA_DICTIONARY.csv", dtype=str, keep_default_na=False)
    assert {"table", "column", "description", "unit", "dtype"}.issubset(dictionary.columns)
    for path in sorted(DATA.glob("*.csv")):
        frame = pd.read_csv(path, nrows=1, dtype=str, keep_default_na=False)
        missing = set(frame.columns) - set(
            dictionary.loc[dictionary["table"].eq(path.name), "column"]
        )
        assert not missing, f"{path.name}: missing dictionary entries {sorted(missing)}"


def test_manifest_hashes_match_files():
    manifest = pd.read_csv(RELEASE / "manifest.csv", dtype=str, keep_default_na=False)
    assert len(manifest) > 0
    assert {"path", "bytes", "sha256"}.issubset(manifest.columns)
    for row in manifest.itertuples():
        path = RELEASE / row.path
        assert path.is_file(), f"manifest path missing: {row.path}"
        assert path.stat().st_size == int(row.bytes)
        assert sha256(path) == row.sha256


def test_no_raw_documents_are_published():
    forbidden = {".pdf", ".xls", ".xlsx", ".zip", ".7z"}
    offenders = [
        path for path in RELEASE.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden
    ]
    assert not offenders, f"raw documents leaked into release: {offenders}"


def test_master_tables_are_unchanged():
    for name, expected in MASTER_HASHES.items():
        assert sha256(ROOT / "data" / "processed" / name) == expected


def test_notebook_is_valid_json():
    notebook = ROOT / "notebooks" / "quickstart.ipynb"
    with notebook.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["nbformat"] == 4
    assert any(cell["cell_type"] == "code" for cell in payload["cells"])


def test_validation_sample_counts():
    validation = read("qa_validation_sample.csv")
    assert len(validation) == 63
    assert validation["table"].value_counts().to_dict() == {
        "lfg_measurements": 48,
        "waste_inflow_annual": 15,
    }
    assert validation["validation_status"].eq("found").sum() == 62
    assert validation["validation_status"].eq("not_found").sum() == 1
