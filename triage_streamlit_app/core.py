"""Pure derivation and validation functions for the triage instrument."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


DOMAIN_FIELDS = (
    "rf_systemic",
    "rf_trismus",
    "rf_swallow",
    "rf_airway",
    "rf_spread",
    "rf_host",
)

PRIMARY_OUTCOME_FIELDS = (
    "urgent_source_control",
    "advanced_airway",
    "critical_care",
    "death_odontogenic",
)


def clean_study_id(value: str) -> str:
    """Normalize a pseudonymous study ID without changing its meaning."""
    return "-".join(value.strip().upper().split())


def derive_map(sbp: float | int | None, dbp: float | int | None) -> float | None:
    """Calculate mean arterial pressure from measured SBP and DBP."""
    if sbp is None or dbp is None:
        return None
    return round((float(sbp) + (2 * float(dbp))) / 3, 1)


def derive_score(domain_values: Iterable[int | None]) -> tuple[int, int | None]:
    """Return number missing and the unweighted score; any missing domain makes score NA."""
    values = list(domain_values)
    if len(values) != 6:
        raise ValueError("Exactly six domain values are required.")
    invalid = [value for value in values if value not in (0, 1, None)]
    if invalid:
        raise ValueError("Domain values must be 0, 1, or None.")
    n_missing = sum(value is None for value in values)
    score = None if n_missing else int(sum(values))
    return n_missing, score


def derive_airway_override(value: int | None) -> int | None:
    if value not in (0, 1, None):
        raise ValueError("Airway domain must be 0, 1, or None.")
    return value


def derive_outcome24(
    component_values: Iterable[int | None], outcome_complete: int | bool
) -> int | None:
    """Derive the primary outcome without treating unverified follow-up as a non-event."""
    values = list(component_values)
    if len(values) != 4:
        raise ValueError("Exactly four primary outcome components are required.")
    invalid = [value for value in values if value not in (0, 1, None)]
    if invalid:
        raise ValueError("Outcome components must be 0, 1, or None.")
    if any(value == 1 for value in values):
        return 1
    if bool(outcome_complete) and all(value == 0 for value in values):
        return 0
    return None


def final_outcome(raw_outcome: int | None, adjudicated_outcome: int | None) -> int | None:
    """Use the final adjudicated result when present; otherwise retain the component result."""
    if raw_outcome not in (0, 1, None) or adjudicated_outcome not in (0, 1, None):
        raise ValueError("Outcome values must be 0, 1, or None.")
    return adjudicated_outcome if adjudicated_outcome is not None else raw_outcome


def validate_form_a(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "id_studi": "ID studi",
        "contact_date": "tanggal kontak",
        "contact_time": "jam kontak",
        "initials": "inisial pengisi",
        "site": "lokasi indeks",
        "unit": "unit",
        "first_presentation": "status presentasi pertama",
    }
    for key, label in required.items():
        if data.get(key) in (None, ""):
            errors.append(f"{label.capitalize()} wajib diisi.")

    if data.get("first_presentation") == 1:
        for key, label in (
            ("age_years", "Usia"),
            ("sex", "Jenis kelamin"),
            ("temp", "Suhu"),
            ("hr", "Nadi"),
            ("rr", "Frekuensi napas"),
            ("sbp", "SBP"),
            ("dbp", "DBP"),
            ("spo2", "SpO2"),
            ("oxygen", "Status oksigen"),
            ("mentation", "ACVPU"),
            ("gcs", "GCS"),
            ("clinical_risk", "Perkiraan risiko klinis"),
            ("initial_plan", "Rencana awal"),
            ("assessment_complete_time", "Waktu penilaian selesai"),
            ("predictor_window_violation", "Status predictor window"),
        ):
            if data.get(key) in (None, ""):
                errors.append(f"{label} wajib diisi untuk episode yang memenuhi skrining.")

        sbp = data.get("sbp")
        dbp = data.get("dbp")
        if sbp is not None and dbp is not None and float(sbp) <= float(dbp):
            errors.append("SBP harus lebih besar daripada DBP; periksa kembali tekanan darah.")

        if data.get("oxygen") == 1 and not data.get("oxygen_device"):
            errors.append("Alat pemberian oksigen wajib dicatat bila pasien mendapat suplementasi.")

        domain_values = [data.get(field) for field in DOMAIN_FIELDS]
        if any(value is None for value in domain_values) and not data.get("rf_missing_reason"):
            errors.append("Alasan TD/NA wajib dipilih bila ada domain yang tidak dapat dinilai.")

    return errors


def validate_form_b(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, label in (
        ("id_studi", "ID studi"),
        ("followup_date", "Tanggal penelusuran"),
        ("followup_time", "Jam selesai"),
        ("assessor", "Penelusur"),
        ("outcome_complete", "Status ascertainment"),
    ):
        if data.get(key) in (None, ""):
            errors.append(f"{label} wajib diisi.")

    source_fields = (
        "source_index_record",
        "source_receiving_record",
        "source_transfer_log",
        "source_receiving_contact",
    )
    if not any(data.get(field) == 1 for field in source_fields):
        errors.append("Pilih sedikitnya satu sumber luaran.")

    for component in PRIMARY_OUTCOME_FIELDS:
        if data.get(component) == 1 and not data.get(f"{component}_facility"):
            errors.append(
                f"Fasilitas pelaksana wajib dicatat untuk {component.replace('_', ' ')} yang terkonfirmasi."
            )

    if data.get("outcome_complete") == 1:
        unknown = [field for field in PRIMARY_OUTCOME_FIELDS if data.get(field) is None]
        if unknown:
            errors.append(
                "Ascertainment tidak dapat disebut lengkap selama masih ada komponen luaran yang belum dapat dipastikan."
            )

    for key, label in (
        ("transfer24", "Status transfer antarfasilitas"),
        ("admission", "Status rawat inap"),
        ("iv_antibiotic", "Status antibiotik intravena"),
        ("bedside_drainage", "Status drainase bedside/local anesthesia"),
    ):
        if data.get(key) is None:
            errors.append(f"{label} wajib diisi.")

    if data.get("transfer24") == 1 and not data.get("transfer_destination"):
        errors.append("Tujuan transfer wajib dicatat bila terjadi transfer antarfasilitas.")

    if data.get("adjudication_agreement") == 0 and data.get("final_decision") is None:
        errors.append("Keputusan akhir wajib diisi bila kedua adjudikator tidak sepakat.")

    return errors
