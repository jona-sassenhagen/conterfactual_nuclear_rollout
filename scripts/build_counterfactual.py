"""Generate historical vs counterfactual nuclear rollout data for visualization."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INPUT_PLANTS = ROOT / "germany_power_plants_1990_complete.csv"
INPUT_FOSSIL_BUILDS = ROOT / "fossil_construction_1990_2025_bnetza.csv"
INPUT_GENERATION = ROOT / "electricity-production-by-source.csv"
INPUT_PLANNED_KONVOIS = ROOT / "planned_konvois.md"
OUTPUT_DATA = ROOT / "data" / "scenario_data.json"
OUTPUT_DATA_WEB = ROOT / "docs" / "data" / "scenario_data.json"

START_YEAR = 1989
END_YEAR = 2025
NUCLEAR_CAPACITY_SEQUENCE = [1410.0]
UNITS_PER_YEAR_PATTERN = [2, 1]  # repeat -> average 1.5 units per year
BUILD_START_YEAR = 1990
EVENT_MONTHS = {
    1: [7],
    2: [4, 10],
    3: [3, 7, 11],
}
PLANNED_KONVOI_MUNICIPALITIES = {
    "Hamm": "Hamm-Uentrop",
    "Biblis": "Biblis",
    "Vahnum": "Dorsten",
    "Pfaffenhofen/Zusam": "Pfaffenhofen an der Zusam",
    "Pleinting": "Vilshofen an der Donau",
    "Borken": "Borken (Hessen)",
}
COGEN_KEYWORDS = (
    "chp",
    "kwk",
    "cogen",
    "cogeneration",
    "fern",
    "warme",
    "w\u00e4rme",
    "heiz",
)
FUEL_PRIORITY = {
    "lignite": 0,
    "hard_coal": 0,
    "oil": 1,
    "natural_gas": 2,
}
RENEWABLE_FREEZE_YEAR = 1998
FOSSIL_FUELS = {"hard_coal", "lignite", "natural_gas", "oil"}
FOSSIL_FUEL_KEYS = ["hard_coal", "lignite", "natural_gas", "oil"]
FUEL_TYPE_MAP = {
    "coal": "hard_coal",
    "hard coal": "hard_coal",
    "hard_coal": "hard_coal",
    "lignite": "lignite",
    "gas": "natural_gas",
    "natural gas": "natural_gas",
    "natural_gas": "natural_gas",
    "oil": "oil",
}
EXCLUDED_FOSSIL_PATTERNS = (
    "HKW",
    "Heiz",
    "Fern",
    "Wärme",
    "KWK",
    "Cogen",
    "CHP",
)
GENERATION_ENTITY = "Germany"
GENERATION_COLUMNS = {
    "coal": "Electricity from coal - TWh",
    "gas": "Electricity from gas - TWh",
    "nuclear": "Electricity from nuclear - TWh",
    "hydro": "Electricity from hydro - TWh",
    "solar": "Electricity from solar - TWh",
    "oil": "Electricity from oil - TWh",
    "wind": "Electricity from wind - TWh",
    "bioenergy": "Electricity from bioenergy - TWh",
    "other_renewables": "Other renewables excluding bioenergy - TWh",
}
FOSSIL_GENERATION_COLUMNS = [
    GENERATION_COLUMNS["coal"],
    GENERATION_COLUMNS["gas"],
    GENERATION_COLUMNS["oil"],
]
RENEWABLE_GENERATION_COLUMNS = [
    GENERATION_COLUMNS["hydro"],
    GENERATION_COLUMNS["solar"],
    GENERATION_COLUMNS["wind"],
    GENERATION_COLUMNS["bioenergy"],
    GENERATION_COLUMNS["other_renewables"],
]
EMISSIONS_FACTORS_TON_PER_MWH = {
    GENERATION_COLUMNS["coal"]: 0.95,
    GENERATION_COLUMNS["gas"]: 0.45,
    GENERATION_COLUMNS["oil"]: 0.78,
    GENERATION_COLUMNS["nuclear"]: 0.01,
    GENERATION_COLUMNS["hydro"]: 0.0,
    GENERATION_COLUMNS["solar"]: 0.0,
    GENERATION_COLUMNS["wind"]: 0.0,
    GENERATION_COLUMNS["bioenergy"]: 0.0,
    GENERATION_COLUMNS["other_renewables"]: 0.0,
}
HOURS_PER_YEAR = 8760
NUCLEAR_CAPACITY_FACTOR = 0.90  # stylised baseload availability


@dataclass
class PlantRecord:
    record_id: int
    name: str
    municipality: str
    fuel_bucket: str
    technology: str
    capacity_mw: float
    commission_year: int | None
    closure_year: int | None
    is_cogeneration: bool = False

    @property
    def descriptor(self) -> str:
        municipality = (self.municipality or "").strip()
        if municipality:
            return f"{self.name} ({municipality})"
        return self.name


def load_plants() -> pd.DataFrame:
    df = pd.read_csv(INPUT_PLANTS)
    df = df[df["technology"] != "aggregate"].copy()
    df["commission_year"] = df["commission_year"].round().astype("Int64")
    df["closure_year"] = df["closure_year"].round().astype("Int64")
    return df


def load_planned_konvois(plants: pd.DataFrame) -> List[Dict[str, str]]:
    if not INPUT_PLANNED_KONVOIS.exists():
        return []

    raw_lines = INPUT_PLANNED_KONVOIS.read_text(encoding="utf-8").splitlines()
    site_names = [line.strip() for line in raw_lines if line.strip()]
    if not site_names:
        return []

    results: List[Dict[str, str]] = []
    for site in site_names:
        municipality = ""
        matches = plants[
            plants["name"].fillna("").str.contains(site, case=False)
            | plants["municipality"].fillna("").str.contains(site, case=False)
        ]

        candidates = [cand.strip() for cand in matches["municipality"].dropna().unique() if str(cand).strip()]
        if len(candidates) == 1:
            municipality = candidates[0]
        elif len(candidates) > 1:
            lowered = site.lower()
            best = [cand for cand in candidates if lowered in cand.lower()]
            municipality = best[0] if best else candidates[0]

        if not municipality:
            municipality = PLANNED_KONVOI_MUNICIPALITIES.get(site, site)

        display_name = f"{site} (Konvoi)" if "konvoi" not in site.lower() else site
        results.append(
            {
                "site": site,
                "display": display_name,
                "municipality": municipality,
            }
        )

    return results


def compute_site_baselines(plants: pd.DataFrame) -> Dict[str, Dict[str, Dict[str, float]]]:
    baselines: Dict[str, Dict[str, Dict[str, float]]] = {"nuclear": {}, "fossil": {}}
    active_mask = (
        (plants["commission_year"].isna() | (plants["commission_year"] <= START_YEAR))
        & (plants["closure_year"].isna() | (plants["closure_year"] >= START_YEAR))
    )
    active_plants = plants[active_mask]
    seen_keys: Dict[str, set] = {"nuclear": set(), "fossil": set()}

    for row in active_plants.itertuples():
        if row.fuel_bucket == "nuclear":
            bucket = "nuclear"
        elif row.fuel_bucket in FOSSIL_FUELS:
            bucket = "fossil"
        else:
            continue

        capacity = float(row.capacity_mw)
        names = set()
        if isinstance(row.name, str) and row.name.strip():
            names.add(row.name.strip())
        if isinstance(row.municipality, str) and row.municipality.strip():
            names.add(f"{row.name.strip()} ({row.municipality.strip()})")

        for key in names:
            uniq = (bucket, key)
            if uniq in seen_keys[bucket]:
                continue
            seen_keys[bucket].add(uniq)
            stats = baselines[bucket].setdefault(key, {"count": 0, "capacity_mw": 0.0})
            stats["count"] += 1
            stats["capacity_mw"] += capacity

    return baselines




def build_municipality_baselines(plants: pd.DataFrame) -> Dict[str, Dict[str, Dict[str, float]]]:
    baselines: Dict[str, Dict[str, Dict[str, float]]] = {"nuclear": {}, "fossil": {}}
    active_mask = (
        (plants["commission_year"].isna() | (plants["commission_year"] <= START_YEAR))
        & (plants["closure_year"].isna() | (plants["closure_year"] >= START_YEAR))
    )
    active_plants = plants[active_mask]
    seen_keys: Dict[str, set] = {"nuclear": set(), "fossil": set()}

    for row in active_plants.itertuples():
        if row.fuel_bucket == "nuclear":
            bucket = "nuclear"
        elif row.fuel_bucket in FOSSIL_FUELS:
            bucket = "fossil"
        else:
            continue

        capacity = float(row.capacity_mw)
        municipality = (row.municipality or "").strip()
        if not municipality:
            continue

        uniq = (bucket, row.name.strip() if isinstance(row.name, str) else municipality)
        if uniq in seen_keys[bucket]:
            continue
        seen_keys[bucket].add(uniq)

        stats = baselines[bucket].setdefault(municipality, {"count": 0, "capacity_mw": 0.0})
        stats["count"] += 1
        stats["capacity_mw"] += capacity

    return baselines


def compute_capacity_by_year(plants: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    years = list(range(start_year, end_year + 1))
    records: List[Dict[str, float]] = []
    for year in years:
        active = plants[
            (plants["commission_year"].isna() | (plants["commission_year"] <= year))
            & (plants["closure_year"].isna() | (plants["closure_year"] >= year))
        ]
        nuclear_mw = active.loc[active["fuel_bucket"] == "nuclear", "capacity_mw"].sum()
        fossil_mw = active.loc[active["fuel_bucket"].isin(FOSSIL_FUELS), "capacity_mw"].sum()
        other_mw = active.loc[
            ~active["fuel_bucket"].isin(FOSSIL_FUELS | {"nuclear"}), "capacity_mw"
        ].sum()
        total_mw = nuclear_mw + fossil_mw + other_mw
        records.append(
            {
                "year": year,
                "nuclear_mw": float(nuclear_mw),
                "fossil_mw": float(fossil_mw),
                "other_mw": float(other_mw),
                "total_mw": float(total_mw),
            }
        )
    return pd.DataFrame(records)


def compute_fossil_breakdown_by_year(plants: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    years = list(range(start_year, end_year + 1))
    rows: List[Dict[str, float]] = []
    for year in years:
        active = plants[
            (plants["commission_year"].isna() | (plants["commission_year"] <= year))
            & (plants["closure_year"].isna() | (plants["closure_year"] >= year))
        ]
        breakdown = {fuel: 0.0 for fuel in FOSSIL_FUEL_KEYS}
        fossil_active = active[active["fuel_bucket"].isin(FOSSIL_FUELS)]
        for row in fossil_active.itertuples():
            fuel = row.fuel_bucket
            breakdown[fuel] += float(row.capacity_mw)
        rows.append(
            {
                "year": year,
                "fossil_hard_coal_mw": breakdown["hard_coal"],
                "fossil_lignite_mw": breakdown["lignite"],
                "fossil_natural_gas_mw": breakdown["natural_gas"],
                "fossil_oil_mw": breakdown["oil"],
            }
        )
    return pd.DataFrame(rows)


def build_fossil_candidate_pools(plants: pd.DataFrame) -> Tuple[List[PlantRecord], List[PlantRecord]]:
    fossil_plants = plants[plants["fuel_bucket"].isin(FOSSIL_FUELS)].copy()

    def as_records(df: pd.DataFrame) -> List[PlantRecord]:
        records: List[PlantRecord] = []
        for row in df.itertuples():
            name_value = row.name if isinstance(row.name, str) else ""
            technology_value = row.technology if isinstance(row.technology, str) else ""
            text_blob = f"{name_value} {technology_value}".lower()
            is_cogen = any(keyword in text_blob for keyword in COGEN_KEYWORDS)
            records.append(
                PlantRecord(
                    record_id=int(row.Index),
                    name=row.name,
                    municipality=row.municipality if isinstance(row.municipality, str) else "",
                    fuel_bucket=row.fuel_bucket,
                    technology=row.technology,
                    capacity_mw=float(row.capacity_mw),
                    commission_year=int(row.commission_year) if pd.notna(row.commission_year) else None,
                    closure_year=int(row.closure_year) if pd.notna(row.closure_year) else None,
                    is_cogeneration=is_cogen,
                )
            )
        records.sort(
            key=lambda record: (
                FUEL_PRIORITY.get(record.fuel_bucket, 3),
                record.is_cogeneration,
                record.commission_year if record.commission_year is not None else 9999,
                record.capacity_mw,
            )
        )
        return records

    mask = pd.Series(True, index=fossil_plants.index)
    for pattern in EXCLUDED_FOSSIL_PATTERNS:
        mask &= ~fossil_plants["name"].str.contains(pattern, case=False, na=False)

    primary = as_records(fossil_plants[mask])
    fallback = as_records(fossil_plants[~mask])
    return primary, fallback


def pick_fossil_closures(
    year: int,
    capacity_needed: float,
    running_fossil: float,
    primary_pool: List[PlantRecord],
    fallback_pool: List[PlantRecord],
    closed_ids: set[int],
) -> Tuple[List[PlantRecord], float]:
    if running_fossil <= 0 or capacity_needed <= 0:
        return [], 0.0
    closings: List[PlantRecord] = []
    total_closed = 0.0
    remaining_needed = max(capacity_needed, 0.0)

    if remaining_needed <= 1e-6:
        return [], 0.0

    def consume(pool: List[PlantRecord]) -> None:
        nonlocal total_closed, remaining_needed
        for record in pool:
            if remaining_needed <= 1e-6:
                break
            if record.record_id in closed_ids:
                continue
            if record.commission_year is not None and record.commission_year > year:
                continue
            if record.closure_year is not None and record.closure_year < year:
                continue
            if record.capacity_mw > remaining_needed + 1e-6:
                continue
            closings.append(record)
            closed_ids.add(record.record_id)
            total_closed += record.capacity_mw
            remaining_needed = max(0.0, capacity_needed - total_closed)
            if remaining_needed <= 1e-6:
                break

    consume(primary_pool)
    if remaining_needed > 1e-6:
        consume(fallback_pool)

    total_closed = min(total_closed, running_fossil)
    return closings, total_closed


def build_counterfactual_events(
    plants: pd.DataFrame,
    actual_capacity: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> Tuple[List[Dict[str, object]], pd.DataFrame]:
    capacity_with_baseline = compute_capacity_by_year(plants, start_year, end_year)
    baseline_row = capacity_with_baseline[capacity_with_baseline["year"] == start_year].iloc[0]

    running_nuclear = baseline_row["nuclear_mw"]
    running_fossil = baseline_row["fossil_mw"]

    primary_pool, fallback_pool = build_fossil_candidate_pools(plants)
    plant_municipality_map: Dict[str, str] = {}
    for row in plants.itertuples():
        if isinstance(row.name, str) and isinstance(row.municipality, str):
            name = row.name.strip()
            municipality = row.municipality.strip()
            plant_municipality_map[name] = municipality
            plant_municipality_map[f"{name} ({municipality})"] = municipality
            plant_municipality_map[municipality] = municipality

    planned_konvois = load_planned_konvois(plants)
    closed_record_ids: set[int] = set()
    baseline_breakdown_df = compute_fossil_breakdown_by_year(plants, start_year, start_year)
    if baseline_breakdown_df.empty:
        running_fossil_breakdown = {fuel: 0.0 for fuel in FOSSIL_FUEL_KEYS}
    else:
        initial_row = baseline_breakdown_df.iloc[0]
        running_fossil_breakdown = {
            "hard_coal": float(initial_row["fossil_hard_coal_mw"]),
            "lignite": float(initial_row["fossil_lignite_mw"]),
            "natural_gas": float(initial_row["fossil_natural_gas_mw"]),
            "oil": float(initial_row["fossil_oil_mw"]),
        }

    existing_nuclear_sites = (
        plants.loc[plants["fuel_bucket"] == "nuclear", "name"].dropna().tolist()
    )
    if not existing_nuclear_sites:
        existing_nuclear_sites = ["Generic Nuclear Complex"]

    municipality_baselines_map = build_municipality_baselines(plants).get("nuclear", {})
    site_unit_counter: Dict[str, int] = {}
    baseline_existing_sites: List[str] = []
    for raw_key, stats in municipality_baselines_map.items():
        canonical = (plant_municipality_map.get(raw_key, "") or raw_key).strip()
        if not canonical:
            canonical = raw_key
        baseline_existing_sites.append(canonical)
        site_unit_counter[canonical] = site_unit_counter.get(canonical, 0) + int(
            stats.get("count", 0)
        )
    if baseline_existing_sites:
        baseline_existing_sites = list(dict.fromkeys(baseline_existing_sites))
    else:
        fallback_labels = [
            (plant_municipality_map.get(name, "") or name).strip()
            for name in existing_nuclear_sites
        ]
        baseline_existing_sites = [label for label in fallback_labels if label]

    existing_site_pattern: Tuple[bool, ...] = (True, True, True, False)
    post_planned_allocation_index = 0

    def choose_existing_municipality() -> str | None:
        if not baseline_existing_sites:
            return None
        return min(
            baseline_existing_sites,
            key=lambda key: (site_unit_counter.get(key, 0), key),
        )

    events: List[Dict[str, object]] = []
    timeseries_rows: List[Dict[str, object]] = []

    nuclear_sequence = NUCLEAR_CAPACITY_SEQUENCE
    seq_len = len(nuclear_sequence)
    nuclear_build_count = 0

    for year in range(start_year, end_year + 1):
        actual_row_year = actual_capacity.loc[actual_capacity["year"] == year]
        if actual_row_year.empty:
            actual_row_year = actual_capacity.iloc[[-1]]
        else:
            actual_row_year = actual_row_year.iloc[[0]]
        year_other_capacity = float(actual_row_year["other_mw"].iloc[0])
        year_total_requirement = float(actual_row_year["total_mw"].iloc[0])

        if year < BUILD_START_YEAR:
            units_this_year = 0
        else:
            pattern_index = (year - BUILD_START_YEAR) % len(UNITS_PER_YEAR_PATTERN)
            units_this_year = UNITS_PER_YEAR_PATTERN[pattern_index]
        for unit_index in range(units_this_year):
            capacity_added = nuclear_sequence[nuclear_build_count % seq_len]
            other_capacity = year_other_capacity
            actual_total_mw = year_total_requirement

            fossil_before_closure = running_fossil
            nuclear_after = running_nuclear + capacity_added
            fossil_floor_mw = max(0.0, actual_total_mw - (nuclear_after + other_capacity))
            allowed_shutdown_mw = max(0.0, fossil_before_closure - fossil_floor_mw)
            closure_target_mw = min(capacity_added, allowed_shutdown_mw)

            if closure_target_mw > 0:
                closings, fossil_closed = pick_fossil_closures(
                    year,
                    closure_target_mw,
                    running_fossil,
                    primary_pool,
                    fallback_pool,
                    closed_record_ids,
                )
            else:
                closings = []
                fossil_closed = 0.0
            if fossil_closed > closure_target_mw + 1e-6:
                for record in closings:
                    closed_record_ids.discard(record.record_id)
                closings = []
                fossil_closed = 0.0
                closure_target_mw = 0.0

            running_nuclear += capacity_added

            residual_closure_mw = 0.0
            if closure_target_mw > 0 and fossil_closed < closure_target_mw:
                residual_closure_mw = closure_target_mw - fossil_closed

            planned_site: Dict[str, str] | None = None
            if nuclear_build_count < len(planned_konvois):
                planned_site = planned_konvois[nuclear_build_count]

            site_label = ""
            site_municipality = ""
            if planned_site:
                site_label = planned_site.get("display", "").strip()
                site_municipality = (planned_site.get("municipality") or "").strip()
            else:
                prefer_existing = False
                if nuclear_build_count >= len(planned_konvois) and existing_site_pattern:
                    prefer_existing = existing_site_pattern[
                        post_planned_allocation_index % len(existing_site_pattern)
                    ]
                    post_planned_allocation_index += 1

                if prefer_existing:
                    chosen_municipality = choose_existing_municipality()
                    if chosen_municipality:
                        site_municipality = chosen_municipality
                        site_label = chosen_municipality

                if not site_label:
                    if closings:
                        primary_closing = closings[0]
                        site_municipality = (
                            primary_closing.municipality.strip()
                            if isinstance(primary_closing.municipality, str)
                            else ""
                        )
                        descriptor_label = primary_closing.descriptor.strip()
                        mapped_municipality = (
                            plant_municipality_map.get(descriptor_label, "") or ""
                        ).strip()
                        if not site_municipality and mapped_municipality:
                            site_municipality = mapped_municipality
                        site_label = site_municipality or descriptor_label
                    else:
                        site_choice = existing_nuclear_sites[
                            nuclear_build_count % len(existing_nuclear_sites)
                        ]
                        mapped_municipality = (
                            plant_municipality_map.get(site_choice, "") or ""
                        ).strip()
                        site_municipality = mapped_municipality
                        site_label = mapped_municipality or site_choice.strip()

            if not site_label:
                site_label = site_municipality or "New Nuclear Complex"

            if not site_municipality:
                site_municipality = (plant_municipality_map.get(site_label, "") or "").strip()

            counter_key = site_municipality or site_label
            current_units = site_unit_counter.get(counter_key, 0) + 1
            site_unit_counter[counter_key] = current_units
            unit_name = f"Unit {current_units}"

            months = EVENT_MONTHS.get(units_this_year, [6, 9, 12])
            month_value = months[min(unit_index, len(months) - 1)]
            event_date = f"{year}-{month_value:02d}-01"
            fossil_sites_closed = [closing.descriptor for closing in closings]
            closure_entries: List[Dict[str, object]] = []
            remaining = fossil_before_closure
            dummy_to_allocate = residual_closure_mw
            if closings:
                for idx, closing in enumerate(closings):
                    extra_dummy = 0.0
                    if dummy_to_allocate > 0 and idx == len(closings) - 1:
                        extra_dummy = dummy_to_allocate
                    decrement = closing.capacity_mw + extra_dummy
                    remaining = max(remaining - decrement, fossil_floor_mw)
                    fuel_bucket = closing.fuel_bucket
                    if fuel_bucket in running_fossil_breakdown:
                        running_fossil_breakdown[fuel_bucket] = max(
                            0.0,
                            running_fossil_breakdown[fuel_bucket] - decrement,
                        )
                    closure_entries.append(
                        {
                            "date": event_date,
                            "year": year,
                            "site": closing.municipality if closing.municipality else closing.descriptor,
                            "name": closing.descriptor,
                            "event_type": "fossil_closure",
                            "fuel": closing.fuel_bucket,
                            "mw_removed": round(closing.capacity_mw, 1),
                            "fossil_capacity_closed_mw": round(closing.capacity_mw + extra_dummy, 1),
                            "dummy_capacity_closed_mw": round(extra_dummy, 1) if extra_dummy else 0.0,
                            "running_fossil_mw": round(remaining, 1),
                            "municipality": closing.municipality,
                        }
                    )
            elif dummy_to_allocate > 0:
                remaining = max(remaining - dummy_to_allocate, fossil_floor_mw)
                total_available = sum(running_fossil_breakdown.values())
                if total_available > 0:
                    for fuel_bucket in running_fossil_breakdown:
                        share = running_fossil_breakdown[fuel_bucket] / total_available
                        running_fossil_breakdown[fuel_bucket] = max(
                            0.0,
                            running_fossil_breakdown[fuel_bucket] - dummy_to_allocate * share,
                        )
                closure_entries.append(
                    {
                        "date": event_date,
                        "year": year,
                        "site": "Residual fossil fleet",
                        "name": "Residual fossil fleet",
                        "event_type": "fossil_closure",
                        "fuel": "fossil",
                        "mw_removed": 0.0,
                        "fossil_capacity_closed_mw": round(dummy_to_allocate, 1),
                        "dummy_capacity_closed_mw": round(dummy_to_allocate, 1),
                        "running_fossil_mw": round(remaining, 1),
                        "municipality": "",
                        "residual_only": True,
                    }
                )
                fossil_sites_closed.append("Residual fossil fleet")
            running_fossil = max(remaining, fossil_floor_mw)
            running_total = running_nuclear + running_fossil + other_capacity
            events.extend(closure_entries)

            actual_closed_mw = fossil_closed + residual_closure_mw
            running_total = running_nuclear + running_fossil + other_capacity
            events.append(
                {
                    "date": event_date,
                    "year": year,
                    "site": site_label,
                    "name": f"{site_label} {unit_name}",
                    "event_type": "nuclear_build",
                    "mw_added": round(capacity_added, 1),
                    "running_nuclear_mw": round(running_nuclear, 1),
                    "running_fossil_mw": round(running_fossil, 1),
                    "running_total_mw": round(running_total, 1),
                    "fossil_sites_closed": fossil_sites_closed,
                    "fossil_capacity_closed_mw": round(actual_closed_mw, 1),
                    "dummy_fossil_capacity_closed_mw": round(residual_closure_mw, 1),
                    "annual_generation_capacity_twh": round(running_total * HOURS_PER_YEAR / 1e6, 2),
                    "municipality": site_municipality,
                }
            )
            nuclear_build_count += 1

        timeseries_rows.append(
            {
                "year": year,
                "nuclear_mw": round(running_nuclear, 1),
                "fossil_mw": round(running_fossil, 1),
                "other_mw": float(
                    actual_capacity.loc[
                        actual_capacity["year"]
                        == min(year, actual_capacity["year"].max()),
                        "other_mw",
                    ].iloc[0]
                ),
                "fossil_hard_coal_mw": round(running_fossil_breakdown.get("hard_coal", 0.0), 1),
                "fossil_lignite_mw": round(running_fossil_breakdown.get("lignite", 0.0), 1),
                "fossil_natural_gas_mw": round(running_fossil_breakdown.get("natural_gas", 0.0), 1),
                "fossil_oil_mw": round(running_fossil_breakdown.get("oil", 0.0), 1),
            }
        )

    timeseries_df = pd.DataFrame(timeseries_rows)
    timeseries_df["total_mw"] = (
        timeseries_df["nuclear_mw"] + timeseries_df["fossil_mw"] + timeseries_df["other_mw"]
    )
    return events, timeseries_df


def apply_fossil_builds_to_capacity(
    capacity: pd.DataFrame,
    fossil_builds: pd.DataFrame,
    start_year: int,
    end_year: int,
    breakdown: pd.DataFrame | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame | None]:
    adjusted = capacity.copy()
    breakdown_adjusted = breakdown.copy() if breakdown is not None else None
    builds = fossil_builds.copy()
    builds["commission_year"] = builds["commission_year"].round().astype("Int64")
    builds = builds[
        (builds["commission_year"] >= start_year)
        & (builds["commission_year"] <= end_year)
    ]
    additions_by_year = builds.groupby("commission_year")["capacity_mw"].sum().to_dict()
    running_add = 0.0
    for idx, row in adjusted.iterrows():
        year = row["year"]
        running_add += float(additions_by_year.get(year, 0.0))
        adjusted.at[idx, "fossil_mw"] += running_add
        adjusted.at[idx, "total_mw"] = (
            adjusted.at[idx, "nuclear_mw"]
            + adjusted.at[idx, "fossil_mw"]
            + adjusted.at[idx, "other_mw"]
        )
    if breakdown_adjusted is not None and not builds.empty:
        breakdown_adjusted = breakdown_adjusted.sort_values("year").reset_index(drop=True)
        for build in builds.itertuples():
            fuel = FUEL_TYPE_MAP.get(str(build.type).lower().strip(), None)
            if fuel is None:
                continue
            mask = breakdown_adjusted["year"] >= int(build.commission_year)
            column = f"fossil_{fuel}_mw"
            if column in breakdown_adjusted.columns:
                breakdown_adjusted.loc[mask, column] += float(build.capacity_mw)
    return adjusted, breakdown_adjusted


def build_historical_events(
    fossil_builds: pd.DataFrame,
    plants: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> List[Dict[str, object]]:
    builds = fossil_builds.copy()
    builds["commission_year"] = builds["commission_year"].round().astype("Int64")
    builds = builds[(builds["commission_year"] >= start_year) & (builds["commission_year"] <= end_year)]
    builds = builds.sort_values(["commission_year", "site", "name"])
    events: List[Dict[str, object]] = []
    running_totals = compute_capacity_by_year(plants, start_year - 1, end_year)

    fossil_capacity_by_year = {
        row.year: row.fossil_mw for row in running_totals.itertuples()
    }
    nuclear_capacity_by_year = {
        row.year: row.nuclear_mw for row in running_totals.itertuples()
    }

    for row in builds.itertuples():
        year = int(row.commission_year)
        running_fossil = fossil_capacity_by_year.get(year, fossil_capacity_by_year[max(fossil_capacity_by_year)])
        municipality = row.municipality if isinstance(row.municipality, str) else ""
        site_label = municipality or (row.site if isinstance(row.site, str) else row.name)
        events.append(
            {
                "date": f"{year}-07-01",
                "year": year,
                "site": site_label,
                "name": row.name,
                "event_type": "fossil_build",
                "fuel": row.type if isinstance(row.type, str) else "fossil",
                "mw_added": round(float(row.capacity_mw), 1),
                "running_fossil_mw": round(float(running_fossil), 1),
                "municipality": municipality,
            }
        )

    closures = plants[
        plants["fuel_bucket"].isin(FOSSIL_FUELS)
        & plants["closure_year"].notna()
        & (plants["closure_year"] >= start_year)
        & (plants["closure_year"] <= end_year)
    ].copy()
    closures = closures.sort_values(["closure_year", "commission_year", "name"])

    for row in closures.itertuples():
        year = int(row.closure_year)
        running_fossil = fossil_capacity_by_year.get(year, fossil_capacity_by_year[max(fossil_capacity_by_year)])
        municipality = row.municipality if isinstance(row.municipality, str) else ""
        site_label = municipality or row.name
        events.append(
            {
                "date": f"{year}-11-01",
                "year": year,
                "site": site_label,
                "name": row.name,
                "event_type": "fossil_closure",
                "fuel": row.fuel_bucket if isinstance(row.fuel_bucket, str) else "fossil",
                "mw_removed": round(float(row.capacity_mw), 1),
                "running_fossil_mw": round(float(running_fossil), 1),
                "municipality": municipality,
            }
        )

    nuclear_closures = plants[
        (plants["fuel_bucket"] == "nuclear")
        & plants["closure_year"].notna()
        & (plants["closure_year"] >= start_year)
        & (plants["closure_year"] <= end_year)
    ].copy()
    nuclear_closures = nuclear_closures.sort_values(["closure_year", "commission_year", "name"])

    for row in nuclear_closures.itertuples():
        year = int(row.closure_year)
        running_nuclear_before = nuclear_capacity_by_year.get(
            year, nuclear_capacity_by_year[max(nuclear_capacity_by_year)]
        )
        running_nuclear_after = max(running_nuclear_before - float(row.capacity_mw), 0.0)
        municipality = row.municipality if isinstance(row.municipality, str) else ""
        site_label = municipality or row.name
        events.append(
            {
                "date": f"{year}-11-15",
                "year": year,
                "site": site_label,
                "name": row.name,
                "event_type": "nuclear_closure",
                "fuel": "nuclear",
                "mw_removed": round(float(row.capacity_mw), 1),
                "running_nuclear_mw": round(float(running_nuclear_after), 1),
                "municipality": municipality,
            }
        )

    events.sort(key=lambda item: (item["year"], item["date"], item.get("name", "")))
    return events


def extend_generation_to_year(generation: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    df = generation.copy()
    min_year = int(df["Year"].min())
    if start_year < min_year:
        first_row = df[df["Year"] == min_year].iloc[0]
        for year in range(min_year - 1, start_year - 1, -1):
            new_row = first_row.copy()
            new_row["Year"] = year
            df = pd.concat([pd.DataFrame([new_row]), df], ignore_index=True)
    df = df[(df["Year"] >= start_year)]
    last_row = df[df["Year"] == df["Year"].max()].iloc[0]
    for year in range(int(df["Year"].max()) + 1, end_year + 1):
        new_row = last_row.copy()
        new_row["Year"] = year
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df[df["Year"] <= end_year]
    return df.reset_index(drop=True)


def compute_emissions_timeseries(
    generation: pd.DataFrame,
    actual_capacity: pd.DataFrame,
    counterfactual_capacity: pd.DataFrame,
    actual_breakdown: pd.DataFrame,
    counterfactual_breakdown: pd.DataFrame,
) -> Dict[str, List[Dict[str, float]]]:
    capacity_lookup_actual = actual_capacity.set_index("year")
    capacity_lookup_cf = counterfactual_capacity.set_index("year")
    breakdown_lookup_actual = actual_breakdown.set_index("year")
    breakdown_lookup_cf = counterfactual_breakdown.set_index("year")

    records_actual: List[Dict[str, float]] = []
    records_counterfactual: List[Dict[str, float]] = []

    fossil_columns = FOSSIL_GENERATION_COLUMNS
    renewable_columns = RENEWABLE_GENERATION_COLUMNS

    if not generation[generation["Year"] == START_YEAR].empty:
        baseline_row = generation[generation["Year"] == START_YEAR].iloc[0]
    else:
        baseline_row = generation.iloc[0]

    freeze_row_df = generation[generation["Year"] == RENEWABLE_FREEZE_YEAR]
    if freeze_row_df.empty:
        freeze_row = baseline_row
    else:
        freeze_row = freeze_row_df.iloc[0]

    def base_value(row, column: str) -> float:
        value = row.get(column, 0.0)
        return float(value) if pd.notna(value) else 0.0

    baseline_nuclear_twh = base_value(baseline_row, GENERATION_COLUMNS["nuclear"])
    baseline_renewables_twh = sum(base_value(baseline_row, column) for column in renewable_columns)
    baseline_fossil_twh = sum(base_value(baseline_row, column) for column in fossil_columns)
    baseline_other_twh = 0.0
    baseline_total_twh = baseline_fossil_twh + baseline_nuclear_twh + baseline_renewables_twh + baseline_other_twh

    renewable_freeze_map = {
        column: base_value(freeze_row, column)
        for column in renewable_columns
    }
    frozen_renewables_total = sum(renewable_freeze_map.values())

    prev_cf_nuclear_twh = baseline_nuclear_twh

    for data in generation.to_dict(orient="records"):
        year = int(data["Year"])

        def get_value(column: str) -> float:
            value = data.get(column, 0.0)
            return float(value) if value == value else 0.0

        fossil_twh = sum(get_value(column) for column in fossil_columns)
        nuclear_actual_twh = get_value(GENERATION_COLUMNS["nuclear"])
        renewables_twh = sum(get_value(column) for column in renewable_columns)
        total_twh = fossil_twh + nuclear_actual_twh + renewables_twh

        co2 = 0.0
        for column, factor in EMISSIONS_FACTORS_TON_PER_MWH.items():
            co2 += get_value(column) * factor
        co2_mt = round(co2, 2)

        records_actual.append(
            {
                "year": year,
                "fossil_twh": round(fossil_twh, 2),
                "nuclear_twh": round(nuclear_actual_twh, 2),
                "renewables_twh": round(renewables_twh, 2),
                "total_twh": round(total_twh, 2),
                "co2_mt": co2_mt,
                "clean_twh": round(nuclear_actual_twh + renewables_twh, 2),
            }
        )

        actual_row = capacity_lookup_actual.loc[year]
        cf_row = capacity_lookup_cf.loc[year]

        additional_nuclear_capacity = max(cf_row["nuclear_mw"] - actual_row["nuclear_mw"], 0.0)
        potential_extra_nuclear_twh = (
            additional_nuclear_capacity
            * HOURS_PER_YEAR
            * NUCLEAR_CAPACITY_FACTOR
            / 1_000_000
        )
        if year <= START_YEAR:
            potential_extra_nuclear_twh = 0.0

        available_max_nuclear_twh = baseline_nuclear_twh + potential_extra_nuclear_twh
        cf_nuclear_twh = max(prev_cf_nuclear_twh, available_max_nuclear_twh)
        if year < RENEWABLE_FREEZE_YEAR:
            cf_renewables_twh = renewables_twh
        else:
            cf_renewables_twh = frozen_renewables_total
        cf_other_twh = baseline_other_twh

        potential_without_fossil = cf_nuclear_twh + cf_renewables_twh + cf_other_twh
        required_total = total_twh
        required_fossil_twh = max(required_total - potential_without_fossil, 0.0)
        cf_fossil_twh = required_fossil_twh
        cf_total_twh = potential_without_fossil + cf_fossil_twh

        breakdown_actual_row = breakdown_lookup_actual.loc[year]
        breakdown_cf_row = breakdown_lookup_cf.loc[year]

        coal_actual_cap = float(
            breakdown_actual_row.get("fossil_hard_coal_mw", 0.0)
            + breakdown_actual_row.get("fossil_lignite_mw", 0.0)
        )
        coal_cf_cap = float(
            breakdown_cf_row.get("fossil_hard_coal_mw", 0.0)
            + breakdown_cf_row.get("fossil_lignite_mw", 0.0)
        )
        gas_actual_cap = float(breakdown_actual_row.get("fossil_natural_gas_mw", 0.0))
        gas_cf_cap = float(breakdown_cf_row.get("fossil_natural_gas_mw", 0.0))
        oil_actual_cap = float(breakdown_actual_row.get("fossil_oil_mw", 0.0))
        oil_cf_cap = float(breakdown_cf_row.get("fossil_oil_mw", 0.0))

        coal_ratio = (coal_cf_cap / coal_actual_cap) if coal_actual_cap > 0 else 0.0
        gas_ratio = (gas_cf_cap / gas_actual_cap) if gas_actual_cap > 0 else 0.0
        oil_ratio = (oil_cf_cap / oil_actual_cap) if oil_actual_cap > 0 else 0.0

        scaled_fossil = {
            GENERATION_COLUMNS["coal"]: get_value(GENERATION_COLUMNS["coal"]) * coal_ratio,
            GENERATION_COLUMNS["gas"]: get_value(GENERATION_COLUMNS["gas"]) * gas_ratio,
            GENERATION_COLUMNS["oil"]: get_value(GENERATION_COLUMNS["oil"]) * oil_ratio,
        }

        scaled_total = sum(scaled_fossil.values())
        if cf_fossil_twh > 0 and scaled_total > 0:
            adjust_factor = cf_fossil_twh / scaled_total
            for key in scaled_fossil:
                scaled_fossil[key] *= adjust_factor
        elif cf_fossil_twh > 0 and scaled_total <= 0:
            cap_total_cf = coal_cf_cap + gas_cf_cap + oil_cf_cap
            if cap_total_cf > 0:
                scaled_fossil[GENERATION_COLUMNS["coal"]] = cf_fossil_twh * (coal_cf_cap / cap_total_cf)
                scaled_fossil[GENERATION_COLUMNS["gas"]] = cf_fossil_twh * (gas_cf_cap / cap_total_cf)
                scaled_fossil[GENERATION_COLUMNS["oil"]] = cf_fossil_twh * (oil_cf_cap / cap_total_cf)
            else:
                for key in scaled_fossil:
                    scaled_fossil[key] = 0.0
                cf_fossil_twh = 0.0
        else:
            for key in scaled_fossil:
                scaled_fossil[key] = 0.0
            cf_fossil_twh = 0.0

        cf_clean_twh = cf_nuclear_twh + cf_renewables_twh

        cf_co2 = 0.0
        for column, factor in EMISSIONS_FACTORS_TON_PER_MWH.items():
            if column == GENERATION_COLUMNS["nuclear"]:
                value_twh = cf_nuclear_twh
            elif column in fossil_columns:
                value_twh = scaled_fossil[column]
            elif column in renewable_columns:
                if year < RENEWABLE_FREEZE_YEAR:
                    value_twh = get_value(column)
                else:
                    value_twh = renewable_freeze_map.get(column, 0.0)
            else:
                value_twh = get_value(column)
            cf_co2 += value_twh * factor
        cf_co2_mt = round(cf_co2, 2)

        records_counterfactual.append(
            {
                "year": year,
                "fossil_twh": round(cf_fossil_twh, 2),
                "nuclear_twh": round(cf_nuclear_twh, 2),
                "renewables_twh": round(cf_renewables_twh, 2),
                "total_twh": round(cf_total_twh, 2),
                "co2_mt": cf_co2_mt,
                "clean_twh": round(cf_clean_twh, 2),
            }
        )

        if year <= START_YEAR:
            records_counterfactual[-1] = records_actual[-1].copy()

        prev_cf_nuclear_twh = cf_nuclear_twh

    return {
        "historical": records_actual,
        "counterfactual": records_counterfactual,
    }


def build_dataset() -> Dict[str, object]:
    plants = load_plants()
    fossil_builds = pd.read_csv(INPUT_FOSSIL_BUILDS)
    actual_capacity = compute_capacity_by_year(plants, START_YEAR, END_YEAR)
    actual_breakdown = compute_fossil_breakdown_by_year(plants, START_YEAR, END_YEAR)
    actual_capacity, actual_breakdown = apply_fossil_builds_to_capacity(
        actual_capacity, fossil_builds, START_YEAR, END_YEAR, breakdown=actual_breakdown
    )
    actual_capacity = actual_capacity.merge(actual_breakdown, on="year", how="left")

    counterfactual_events, counterfactual_capacity = build_counterfactual_events(
        plants, actual_capacity, START_YEAR, END_YEAR
    )
    counterfactual_breakdown = counterfactual_capacity[[
        "year",
        "fossil_hard_coal_mw",
        "fossil_lignite_mw",
        "fossil_natural_gas_mw",
        "fossil_oil_mw",
    ]].copy()

    historical_events = build_historical_events(fossil_builds, plants, START_YEAR, END_YEAR)

    generation = pd.read_csv(INPUT_GENERATION)
    generation = generation[generation["Entity"] == GENERATION_ENTITY].copy()
    generation_extended = extend_generation_to_year(generation, START_YEAR, END_YEAR)
    emissions = compute_emissions_timeseries(
        generation_extended,
        actual_capacity,
        counterfactual_capacity,
        actual_breakdown,
        counterfactual_breakdown,
    )

    baselines = compute_site_baselines(plants)
    municipality_baselines = build_municipality_baselines(plants)

    dataset = {
        "historical": {
            "capacity_timeseries": actual_capacity.to_dict(orient="records"),
            "events": historical_events,
            "emissions": emissions["historical"],
        },
        "counterfactual": {
            "capacity_timeseries": counterfactual_capacity.to_dict(orient="records"),
            "events": counterfactual_events,
            "emissions": emissions["counterfactual"],
        },
        "metadata": {
            "start_year": START_YEAR,
            "end_year": END_YEAR,
            "notes": [
                "Nuclear unit capacities cycle through 1980s German reactor sizes.",
                "Fossil closures prioritise the oldest non-CHP plants still online each year.",
                "Historical generation uses Our World in Data's electricity-production-by-source dataset.",
                "Emission factors are approximate tonnes CO2 per MWh for each fuel group.",
            ],
            "site_baselines": baselines,
            "municipality_baselines": municipality_baselines,
        },
    }
    return dataset


def main() -> None:
    dataset = build_dataset()
    payload = json.dumps(dataset, indent=2)

    OUTPUT_DATA.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_DATA.write_text(payload)

    OUTPUT_DATA_WEB.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_DATA_WEB.write_text(payload)

    print(f"Wrote {OUTPUT_DATA.relative_to(ROOT)}")
    print(f"Wrote {OUTPUT_DATA_WEB.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
def build_municipality_baselines(plants: pd.DataFrame) -> Dict[str, Dict[str, Dict[str, float]]]:
    baselines: Dict[str, Dict[str, Dict[str, float]]] = {"nuclear": {}, "fossil": {}}
    active_mask = (
        (plants["commission_year"].isna() | (plants["commission_year"] <= START_YEAR))
        & (plants["closure_year"].isna() | (plants["closure_year"] >= START_YEAR))
    )
    active_plants = plants[active_mask]

    for row in active_plants.itertuples():
        if row.fuel_bucket == "nuclear":
            bucket = "nuclear"
        elif row.fuel_bucket in FOSSIL_FUELS:
            bucket = "fossil"
        else:
            continue

        capacity = float(row.capacity_mw)
        municipality = (row.municipality or "").strip()
        if not municipality:
            continue

        stats = baselines[bucket].setdefault(municipality, {"count": 0, "capacity_mw": 0.0})
        stats["count"] += 1
        stats["capacity_mw"] += capacity

    return baselines
