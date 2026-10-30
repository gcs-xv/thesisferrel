from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from core import (
    DOMAIN_FIELDS,
    PRIMARY_OUTCOME_FIELDS,
    clean_study_id,
    derive_airway_override,
    derive_map,
    derive_outcome24,
    derive_score,
    final_outcome,
    validate_form_a,
    validate_form_b,
)
from data_dictionary import DATA_DICTIONARY
from database import (
    get_all_episodes,
    get_engine,
    get_episode,
    list_episode_ids,
    normalize_database_url,
    upsert_episode,
    utc_now,
)


APP_DIR = Path(__file__).resolve().parent
SITE_LABELS = {1: "RSGM Unhas", 2: "RSPTN Unhas"}
SEX_LABELS = {1: "Laki-laki", 2: "Perempuan"}
DOMAIN_OPTIONS = {
    "Tidak ada (0)": 0,
    "Ada (1)": 1,
    "Tidak dapat dinilai (NA)": None,
}
EVENT_OPTIONS = {
    "Belum/tidak dapat dipastikan (NA)": None,
    "Tidak (0)": 0,
    "Ya (1)": 1,
}
YES_NO_OPTIONS = {"Tidak (0)": 0, "Ya (1)": 1}


st.set_page_config(
    page_title="Instrumen Triage Infeksi Odontogenik",
    page_icon="🦷",
    layout="wide",
)


def secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return str(value) if value not in (None, "") else None


def authenticate() -> None:
    expected_plain = secret("APP_PASSWORD")
    expected_hash = secret("APP_PASSWORD_SHA256")
    if not expected_plain and not expected_hash:
        st.sidebar.warning("Mode lokal tanpa kata sandi. Atur APP_PASSWORD sebelum deployment.")
        return
    if st.session_state.get("authenticated"):
        return

    st.title("Akses instrumen penelitian")
    with st.form("login_form"):
        password = st.text_input("Kata sandi", type="password")
        submitted = st.form_submit_button("Masuk", type="primary")
    if submitted:
        supplied_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        valid = False
        if expected_hash:
            valid = hmac.compare_digest(supplied_hash, expected_hash.lower())
        elif expected_plain:
            valid = hmac.compare_digest(password, expected_plain)
        if valid:
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Kata sandi tidak sesuai.")
    st.stop()


def index_for(mapping: dict[str, Any], stored: Any) -> int | None:
    for index, value in enumerate(mapping.values()):
        if value == stored and not (stored is None and value is not None):
            return index
    return None


def option_index(options: list[str], stored: str | None) -> int | None:
    try:
        return options.index(stored) if stored else None
    except ValueError:
        return None


def date_value(value: str | None, fallback: date | None = None) -> date | None:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return fallback


def time_string(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value).strip()
    return text or None


def date_string(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def validate_optional_clock(value: str | None, label: str, errors: list[str]) -> str | None:
    cleaned = clean_optional_text(value)
    if cleaned and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", cleaned):
        errors.append(f"{label} harus memakai format 24 jam HH:MM, misalnya 08:35.")
    return cleaned


def number_default(record: dict[str, Any], field: str) -> int | float | None:
    value = record.get(field)
    return value if value is not None else None


authenticate()

database_url = normalize_database_url(
    secret("DATABASE_URL") or os.getenv("DATABASE_URL"), APP_DIR
)
try:
    engine = get_engine(database_url)
except Exception as exc:
    st.error("Koneksi basis data gagal. Periksa DATABASE_URL dan Streamlit Secrets.")
    st.exception(exc)
    st.stop()

using_sqlite = database_url.startswith("sqlite")

st.sidebar.title("Instrumen penelitian")
page = st.sidebar.radio(
    "Menu",
    ["Form A", "Form B", "Rekap dan ekspor", "Petunjuk"],
)
st.sidebar.caption("Tidak menyimpan nama pasien atau nomor rekam medis.")
if using_sqlite:
    st.sidebar.caption("Penyimpanan: SQLite lokal")
else:
    st.sidebar.caption("Penyimpanan: PostgreSQL")


def render_form_a() -> None:
    st.title("Form A Kontak Pertama")
    st.caption(
        "Isi berdasarkan informasi pada kontak pertama, sebelum hasil laboratorium, pencitraan, dan keputusan disposisi. "
        "Skor dihitung otomatis tetapi tidak ditampilkan kepada klinisi selama validasi silent."
    )

    ids = list_episode_ids(engine)
    mode = st.radio("Mode entri", ["Entri baru", "Edit entri tersimpan"], horizontal=True)
    record: dict[str, Any] = {}
    selected_id: str | None = None
    if mode == "Edit entri tersimpan":
        if not ids:
            st.info("Belum ada entri untuk diedit.")
            return
        selected_id = st.selectbox("Pilih ID studi", ids)
        record = get_episode(engine, selected_id) or {}
        st.info("Anda sedang memperbarui entri yang sudah tersimpan.")

    form_key = f"form_a_{mode}_{selected_id or 'new'}"
    with st.form(form_key, enter_to_submit=False):
        st.subheader("Identitas episode")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            id_studi = st.text_input(
                "ID studi *",
                value=record.get("id_studi", ""),
                disabled=mode == "Edit entri tersimpan",
                help="Gunakan kode pseudonim. Jangan isi nama atau nomor rekam medis.",
            )
        with c2:
            contact_date = st.date_input(
                "Tanggal kontak *",
                value=date_value(record.get("contact_date"), date.today()),
                format="DD/MM/YYYY",
            )
        with c3:
            default_clock = datetime.now().time().replace(second=0, microsecond=0)
            stored_clock = record.get("contact_time")
            contact_time = st.time_input(
                "Jam kontak *",
                value=(
                    datetime.strptime(stored_clock, "%H:%M").time()
                    if stored_clock
                    else default_clock
                ),
            )
        with c4:
            initials = st.text_input("Inisial pengisi *", value=record.get("initials", ""))

        c1, c2, c3 = st.columns(3)
        with c1:
            site_labels = list(SITE_LABELS.values())
            stored_site = SITE_LABELS.get(record.get("site"))
            site_label = st.selectbox(
                "Lokasi indeks *", site_labels, index=option_index(site_labels, stored_site)
            )
        with c2:
            unit_options = ["IGD", "Poliklinik BM"]
            unit = st.selectbox(
                "Unit *", unit_options, index=option_index(unit_options, record.get("unit"))
            )
        with c3:
            first_label = st.radio(
                "Presentasi pertama episode ini *",
                list(YES_NO_OPTIONS),
                index=index_for(YES_NO_OPTIONS, record.get("first_presentation")),
                horizontal=True,
            )

        st.subheader("A Fisiologis")
        c1, c2 = st.columns(2)
        with c1:
            age_years = st.number_input(
                "Usia (tahun) *", min_value=0.0, max_value=120.0, value=number_default(record, "age_years"), step=1.0
            )
        with c2:
            sex_labels = list(SEX_LABELS.values())
            sex_label = st.selectbox(
                "Jenis kelamin *",
                sex_labels,
                index=option_index(sex_labels, SEX_LABELS.get(record.get("sex"))),
            )

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            temp = st.number_input("Suhu °C *", min_value=25.0, max_value=45.0, value=number_default(record, "temp"), step=0.1)
        with c2:
            hr = st.number_input("Nadi/menit *", min_value=20, max_value=250, value=number_default(record, "hr"), step=1)
        with c3:
            rr = st.number_input("Napas/menit *", min_value=4, max_value=80, value=number_default(record, "rr"), step=1)
        with c4:
            sbp = st.number_input("SBP mmHg *", min_value=40, max_value=300, value=number_default(record, "sbp"), step=1)
        with c5:
            dbp = st.number_input("DBP mmHg *", min_value=20, max_value=200, value=number_default(record, "dbp"), step=1)
        with c6:
            spo2 = st.number_input("SpO₂ % *", min_value=40, max_value=100, value=number_default(record, "spo2"), step=1)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            oxygen_label = st.radio(
                "Oksigen saat dinilai *",
                ["Udara ruangan (0)", "Suplementasi (1)"],
                index=(record.get("oxygen") if record.get("oxygen") in (0, 1) else None),
            )
            oxygen = 0 if oxygen_label == "Udara ruangan (0)" else 1 if oxygen_label else None
        with c2:
            oxygen_flow = st.number_input(
                "Aliran O₂ (L/menit)", min_value=0.0, max_value=60.0, value=number_default(record, "oxygen_flow"), step=0.5
            )
        with c3:
            oxygen_device = st.text_input("Alat O₂", value=record.get("oxygen_device") or "")
        with c4:
            mentation_options = ["A", "C", "V", "P", "U"]
            mentation = st.selectbox(
                "ACVPU *", mentation_options, index=option_index(mentation_options, record.get("mentation"))
            )
            gcs = st.number_input("GCS /15 *", min_value=3, max_value=15, value=number_default(record, "gcs"), step=1)

        st.subheader("B Enam domain")
        st.caption("Pilih TD/NA bila domain benar-benar tidak dapat dinilai; jangan mengubahnya menjadi 0 atau angka sentinel.")
        domain_definitions = [
            ("rf_systemic", "1 Toksisitas sistemik", "Suhu ≥38°C atau <36°C, menggigil, tampak toksik, nadi >90, napas >20, atau SBP <90."),
            ("rf_trismus", "2 Trismus", "Pembukaan mulut terbatas secara klinis atau jarak interinsisal <25 mm."),
            ("rf_swallow", "3 Gangguan menelan", "Disfagia, odinofagia bermakna, drooling, atau tidak mampu menangani sekret."),
            ("rf_airway", "4 Airway breathing voice", "Dispnea, stridor, suara berubah/muffled, drooling karena airway, atau kekhawatiran patensi jalan napas."),
            ("rf_spread", "5 Penyebaran anatomis", "Bengkak progresif/difus, dasar mulut, submandibula bilateral, leher, melewati garis tengah, atau ≥3 spasia."),
            ("rf_host", "6 Kerentanan host", "Diabetes, terapi imunosupresif, keganasan aktif, HIV/imunodefisiensi, transplantasi, atau kondisi immunocompromised lain."),
        ]
        domain_labels: dict[str, str | None] = {}
        for field, label, help_text in domain_definitions:
            domain_labels[field] = st.radio(
                label,
                list(DOMAIN_OPTIONS),
                index=(index_for(DOMAIN_OPTIONS, record.get(field)) if field in record else None),
                horizontal=True,
                help=help_text,
            )

        c1, c2 = st.columns(2)
        with c1:
            missing_reasons = ["Tidak terdokumentasi", "Tidak dapat diperiksa", "Kendala teknis", "Lainnya"]
            missing_reason = st.selectbox(
                "Alasan TD/NA bila ada",
                missing_reasons,
                index=option_index(missing_reasons, record.get("rf_missing_reason")),
                placeholder="Pilih bila ada domain TD/NA",
            )
        with c2:
            missing_reason_other = st.text_input(
                "Rincian alasan lainnya", value=record.get("rf_missing_reason_other") or ""
            )

        st.subheader("C Penilaian klinisi sebelum hasil penunjang")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            clinical_options = ["Rendah", "Sedang", "Tinggi"]
            clinical_risk = st.selectbox(
                "Perkiraan risiko klinis *",
                clinical_options,
                index=option_index(clinical_options, record.get("clinical_risk")),
            )
        with c2:
            plan_options = ["Rawat jalan", "Observasi", "Rawat inap", "Tindakan segera", "Transfer"]
            initial_plan = st.selectbox(
                "Rencana awal *", plan_options, index=option_index(plan_options, record.get("initial_plan"))
            )
        with c3:
            stored_assessment_time = record.get("assessment_complete_time")
            assessment_complete_time = st.time_input(
                "Waktu penilaian selesai *",
                value=(
                    datetime.strptime(stored_assessment_time, "%H:%M").time()
                    if stored_assessment_time
                    else datetime.now().time().replace(second=0, microsecond=0)
                ),
            )
        with c4:
            violation_label = st.radio(
                "Hasil lab/imaging sudah tersedia? *",
                ["Tidak (0)", "Ya — pelanggaran predictor window (1)"],
                index=(record.get("predictor_window_violation") if record.get("predictor_window_violation") in (0, 1) else None),
            )
            predictor_window_violation = (
                0 if violation_label == "Tidak (0)" else 1 if violation_label else None
            )

        submitted = st.form_submit_button("Simpan Form A", type="primary")

    if not submitted:
        return

    normalized_id = clean_study_id(id_studi)
    site = next((code for code, label in SITE_LABELS.items() if label == site_label), None)
    sex = next((code for code, label in SEX_LABELS.items() if label == sex_label), None)
    first_presentation = YES_NO_OPTIONS.get(first_label)
    domain_values = {field: DOMAIN_OPTIONS.get(label) for field, label in domain_labels.items()}
    n_missing, score = derive_score(domain_values.values())

    data = {
        "id_studi": normalized_id,
        "contact_date": date_string(contact_date),
        "contact_time": time_string(contact_time),
        "initials": clean_optional_text(initials),
        "site": site,
        "unit": unit,
        "first_presentation": first_presentation,
        "age_years": age_years,
        "sex": sex,
        "temp": temp,
        "hr": hr,
        "rr": rr,
        "sbp": sbp,
        "dbp": dbp,
        "map": derive_map(sbp, dbp),
        "spo2": spo2,
        "oxygen": oxygen,
        "oxygen_flow": oxygen_flow if oxygen == 1 else None,
        "oxygen_device": clean_optional_text(oxygen_device) if oxygen == 1 else None,
        "mentation": mentation,
        "gcs": gcs,
        **domain_values,
        "rf_n_missing": n_missing,
        "rf_score": score,
        "rf_airway_override": derive_airway_override(domain_values["rf_airway"]),
        "rf_missing_reason": missing_reason if n_missing else None,
        "rf_missing_reason_other": clean_optional_text(missing_reason_other) if n_missing else None,
        "clinical_risk": clinical_risk,
        "initial_plan": initial_plan,
        "assessment_complete_time": time_string(assessment_complete_time),
        "predictor_window_violation": predictor_window_violation,
    }
    errors = validate_form_a(data)
    if mode == "Entri baru" and normalized_id and get_episode(engine, normalized_id):
        errors.append("ID studi sudah ada. Gunakan mode Edit entri tersimpan agar tidak menimpa data.")
    if errors:
        for error in errors:
            st.error(error)
        return

    data["form_a_complete"] = 1 if first_presentation == 1 else 0
    data["form_a_saved_at"] = utc_now()
    upsert_episode(engine, data)
    if first_presentation == 0:
        st.warning("Skrining tersimpan. Episode ditandai tidak eligible dan pengisian dihentikan.")
    else:
        st.success("Form A tersimpan. Skor turunan disimpan secara tersamar dan tidak ditampilkan di sini.")


def event_input(prefix: str, label: str, record: dict[str, Any]) -> tuple[int | None, str | None, str | None]:
    st.markdown(f"**{label}**")
    c1, c2, c3 = st.columns([1.4, 1, 2])
    with c1:
        selection = st.radio(
            f"Status {label}",
            list(EVENT_OPTIONS),
            index=index_for(EVENT_OPTIONS, record.get(prefix)),
            horizontal=False,
            label_visibility="collapsed",
            key=f"{prefix}_status",
        )
    with c2:
        clock = st.text_input(
            "Jam HH:MM",
            value=record.get(f"{prefix}_time") or "",
            key=f"{prefix}_clock",
            placeholder="HH:MM",
        )
    with c3:
        facility = st.text_input(
            "Fasilitas pelaksana",
            value=record.get(f"{prefix}_facility") or "",
            key=f"{prefix}_facility_widget",
        )
    return EVENT_OPTIONS.get(selection), clean_optional_text(clock), clean_optional_text(facility)


def render_form_b() -> None:
    st.title("Form B Luaran Episode")
    st.caption(
        "Penelusuran dilakukan terpisah dari penilaian awal. Transfer saja bukan luaran primer; kejadian high-acuity harus dikonfirmasi di fasilitas penerima."
    )
    ids = list_episode_ids(engine, require_form_a=True)
    if not ids:
        st.info("Belum ada Form A lengkap. Simpan Form A terlebih dahulu.")
        return
    selected_id = st.selectbox("ID studi", ids)
    record = get_episode(engine, selected_id) or {}
    st.caption(
        f"Lokasi indeks: {SITE_LABELS.get(record.get('site'), '—')} | Tanggal kontak: {record.get('contact_date') or '—'}"
    )

    with st.form(f"form_b_{selected_id}", enter_to_submit=False):
        st.subheader("Penelusuran dan sumber")
        c1, c2, c3 = st.columns(3)
        with c1:
            followup_date = st.date_input(
                "Tanggal penelusuran *",
                value=date_value(record.get("followup_date"), date.today()),
                format="DD/MM/YYYY",
            )
        with c2:
            followup_time = st.text_input(
                "Jam selesai (HH:MM) *",
                value=record.get("followup_time") or "",
                placeholder="HH:MM",
            )
        with c3:
            assessor = st.text_input("Inisial penelusur *", value=record.get("assessor") or "")

        st.markdown("**Sumber luaran**")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            source_index_record = st.checkbox("Rekam medis indeks", value=record.get("source_index_record") == 1)
        with c2:
            source_receiving_record = st.checkbox("Rekam medis penerima", value=record.get("source_receiving_record") == 1)
        with c3:
            source_transfer_log = st.checkbox("Log transfer", value=record.get("source_transfer_log") == 1)
        with c4:
            source_receiving_contact = st.checkbox("Kontak fasilitas penerima", value=record.get("source_receiving_contact") == 1)

        ascertainment_map = {
            "Lengkap (1)": 1,
            "Tidak lengkap / indeterminate (0)": 0,
        }
        ascertainment_label = st.radio(
            "Status ascertainment 24 jam *",
            list(ascertainment_map),
            index=index_for(ascertainment_map, record.get("outcome_complete")),
            horizontal=True,
        )

        st.subheader("A Eskalasi manajemen dalam 24 jam")
        urgent_source_control, urgent_source_control_time, urgent_source_control_facility = event_input(
            "urgent_source_control", "Urgent source control di kamar operasi atau dengan general anesthesia", record
        )
        advanced_airway, advanced_airway_time, advanced_airway_facility = event_input(
            "advanced_airway", "Advanced airway management termasuk intubasi sulit atau surgical airway", record
        )
        critical_care, critical_care_time, critical_care_facility = event_input(
            "critical_care", "HCU/ICU, ventilasi invasif, atau vasopresor", record
        )
        death_odontogenic, death_odontogenic_time, death_odontogenic_facility = event_input(
            "death_odontogenic", "Kematian terkait infeksi odontogenik", record
        )

        st.subheader("B Transfer dan luaran sistem pelayanan")
        transfer_label = st.radio(
            "Transfer antarfasilitas *",
            list(YES_NO_OPTIONS),
            index=index_for(YES_NO_OPTIONS, record.get("transfer24")),
            horizontal=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            transfer_destination = st.text_input("Tujuan transfer", value=record.get("transfer_destination") or "")
        with c2:
            transfer_time = st.text_input("Jam transfer (HH:MM)", value=record.get("transfer_time") or "", placeholder="HH:MM")

        reason_options = {
            "Airway": "transfer_reason_airway",
            "Sepsis": "transfer_reason_sepsis",
            "Perlu OR atau GA": "transfer_reason_or_ga",
            "ICU tidak tersedia": "transfer_reason_no_icu",
            "Anestesi atau OR tidak tersedia": "transfer_reason_no_anesthesia_or",
            "Lainnya": "transfer_reason_other",
        }
        default_reasons = [label for label, field in reason_options.items() if record.get(field) == 1]
        transfer_reasons = st.multiselect("Alasan utama transfer", list(reason_options), default=default_reasons)
        transfer_reason_other_text = st.text_input(
            "Rincian alasan lainnya", value=record.get("transfer_reason_other_text") or ""
        )

        st.subheader("C Luaran sekunder")
        c1, c2 = st.columns(2)
        with c1:
            admission_label = st.radio(
                "Rawat inap", list(YES_NO_OPTIONS), index=index_for(YES_NO_OPTIONS, record.get("admission")), horizontal=True
            )
            los_days = st.number_input("Lama rawat (hari)", min_value=0.0, max_value=365.0, value=number_default(record, "los_days"), step=0.5)
            iv_antibiotic_label = st.radio(
                "Antibiotik intravena", list(YES_NO_OPTIONS), index=index_for(YES_NO_OPTIONS, record.get("iv_antibiotic")), horizontal=True
            )
            iv_antibiotic_time = st.text_input("Jam mulai antibiotik IV (HH:MM)", value=record.get("iv_antibiotic_time") or "", placeholder="HH:MM")
        with c2:
            bedside_label = st.radio(
                "Drainase bedside / local anesthesia", list(YES_NO_OPTIONS), index=index_for(YES_NO_OPTIONS, record.get("bedside_drainage")), horizontal=True
            )
            bedside_drainage_type = st.text_input("Jenis drainase", value=record.get("bedside_drainage_type") or "")
            revisit_label = st.radio(
                "Kunjungan ulang atau readmisi 7 hari",
                list(EVENT_OPTIONS),
                index=index_for(EVENT_OPTIONS, record.get("revisit7")),
                horizontal=True,
                help="Boleh dibiarkan NA sampai penelusuran hari ke-7 selesai.",
            )
            revisit7_date = st.date_input(
                "Tanggal kunjungan ulang",
                value=date_value(record.get("revisit7_date"), None),
                format="DD/MM/YYYY",
            )

        st.subheader("D Adjudikasi")
        st.caption("Bagian ini dapat diisi setelah review adjudikator. NA berarti indeterminate atau belum ditetapkan.")
        c1, c2, c3 = st.columns(3)
        with c1:
            adjudicator_a_label = st.radio(
                "Adjudikator A", list(EVENT_OPTIONS), index=index_for(EVENT_OPTIONS, record.get("adjudicator_a")), horizontal=True
            )
        with c2:
            adjudicator_b_label = st.radio(
                "Adjudikator B", list(EVENT_OPTIONS), index=index_for(EVENT_OPTIONS, record.get("adjudicator_b")), horizontal=True
            )
        with c3:
            final_decision_label = st.radio(
                "Keputusan final", list(EVENT_OPTIONS), index=index_for(EVENT_OPTIONS, record.get("final_decision")), horizontal=True
            )

        submitted = st.form_submit_button("Simpan Form B", type="primary")

    if not submitted:
        return

    followup_time_clean = clean_optional_text(followup_time)
    transfer_time_clean = clean_optional_text(transfer_time)
    iv_time_clean = clean_optional_text(iv_antibiotic_time)
    transfer24 = YES_NO_OPTIONS.get(transfer_label)
    admission = YES_NO_OPTIONS.get(admission_label)
    iv_antibiotic = YES_NO_OPTIONS.get(iv_antibiotic_label)
    bedside_drainage = YES_NO_OPTIONS.get(bedside_label)
    clock_errors: list[str] = []
    followup_time_clean = validate_optional_clock(followup_time_clean, "Jam penelusuran", clock_errors)
    if urgent_source_control == 1:
        urgent_source_control_time = validate_optional_clock(urgent_source_control_time, "Jam urgent source control", clock_errors)
    if advanced_airway == 1:
        advanced_airway_time = validate_optional_clock(advanced_airway_time, "Jam advanced airway", clock_errors)
    if critical_care == 1:
        critical_care_time = validate_optional_clock(critical_care_time, "Jam critical care", clock_errors)
    if death_odontogenic == 1:
        death_odontogenic_time = validate_optional_clock(death_odontogenic_time, "Jam kematian", clock_errors)
    if transfer24 == 1:
        transfer_time_clean = validate_optional_clock(transfer_time_clean, "Jam transfer", clock_errors)
    if iv_antibiotic == 1:
        iv_time_clean = validate_optional_clock(iv_time_clean, "Jam antibiotik IV", clock_errors)

    adjudicator_a = EVENT_OPTIONS.get(adjudicator_a_label)
    adjudicator_b = EVENT_OPTIONS.get(adjudicator_b_label)
    agreement = (
        int(adjudicator_a == adjudicator_b)
        if adjudicator_a in (0, 1) and adjudicator_b in (0, 1)
        else None
    )
    outcome_complete = ascertainment_map.get(ascertainment_label)
    component_values = [urgent_source_control, advanced_airway, critical_care, death_odontogenic]
    raw_outcome = derive_outcome24(component_values, outcome_complete or 0)
    final_decision = EVENT_OPTIONS.get(final_decision_label)

    data = {
        "id_studi": selected_id,
        "followup_date": date_string(followup_date),
        "followup_time": followup_time_clean,
        "assessor": clean_optional_text(assessor),
        "source_index_record": int(source_index_record),
        "source_receiving_record": int(source_receiving_record),
        "source_transfer_log": int(source_transfer_log),
        "source_receiving_contact": int(source_receiving_contact),
        "outcome_complete": outcome_complete,
        "urgent_source_control": urgent_source_control,
        "urgent_source_control_time": urgent_source_control_time if urgent_source_control == 1 else None,
        "urgent_source_control_facility": urgent_source_control_facility if urgent_source_control == 1 else None,
        "advanced_airway": advanced_airway,
        "advanced_airway_time": advanced_airway_time if advanced_airway == 1 else None,
        "advanced_airway_facility": advanced_airway_facility if advanced_airway == 1 else None,
        "critical_care": critical_care,
        "critical_care_time": critical_care_time if critical_care == 1 else None,
        "critical_care_facility": critical_care_facility if critical_care == 1 else None,
        "death_odontogenic": death_odontogenic,
        "death_odontogenic_time": death_odontogenic_time if death_odontogenic == 1 else None,
        "death_odontogenic_facility": death_odontogenic_facility if death_odontogenic == 1 else None,
        "outcome24_raw": raw_outcome,
        "outcome24": final_outcome(raw_outcome, final_decision),
        "transfer24": transfer24,
        "transfer_destination": clean_optional_text(transfer_destination) if transfer24 == 1 else None,
        "transfer_time": transfer_time_clean if transfer24 == 1 else None,
        **{field: int(transfer24 == 1 and label in transfer_reasons) for label, field in reason_options.items()},
        "transfer_reason_other_text": clean_optional_text(transfer_reason_other_text) if transfer24 == 1 and "Lainnya" in transfer_reasons else None,
        "admission": admission,
        "los_days": los_days if admission == 1 else None,
        "iv_antibiotic": iv_antibiotic,
        "iv_antibiotic_time": iv_time_clean if iv_antibiotic == 1 else None,
        "bedside_drainage": bedside_drainage,
        "bedside_drainage_type": clean_optional_text(bedside_drainage_type) if bedside_drainage == 1 else None,
        "revisit7": EVENT_OPTIONS.get(revisit_label),
        "revisit7_date": date_string(revisit7_date),
        "adjudicator_a": adjudicator_a,
        "adjudicator_b": adjudicator_b,
        "adjudication_agreement": agreement,
        "final_decision": final_decision,
    }
    errors = clock_errors + validate_form_b(data)
    if errors:
        for error in errors:
            st.error(error)
        return

    data["form_b_complete"] = 1
    data["form_b_saved_at"] = utc_now()
    upsert_episode(engine, data)
    st.success("Form B tersimpan. Luaran indeterminate tetap disimpan sebagai NA, bukan non-event.")


def render_recap() -> None:
    st.title("Rekap dan Ekspor")
    rows = get_all_episodes(engine)
    if not rows:
        st.info("Belum ada data tersimpan.")
        return
    frame = pd.DataFrame(rows)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Semua episode", len(frame))
    c2.metric("Form A lengkap", int((frame["form_a_complete"] == 1).sum()))
    c3.metric("Form B tersimpan", int((frame["form_b_complete"] == 1).sum()))
    c4.metric("Luaran primer terkonfirmasi", int((frame["outcome24"] == 1).sum()))

    st.subheader("Filter tampilan")
    c1, c2 = st.columns(2)
    with c1:
        site_filter = st.multiselect("Lokasi indeks", list(SITE_LABELS.values()), default=list(SITE_LABELS.values()))
    with c2:
        status_filter = st.selectbox("Status data", ["Semua", "Form A lengkap", "Form B lengkap", "Analysis-ready"])

    filtered = frame.copy()
    selected_site_codes = [code for code, label in SITE_LABELS.items() if label in site_filter]
    filtered = filtered[filtered["site"].isin(selected_site_codes)]
    if status_filter == "Form A lengkap":
        filtered = filtered[filtered["form_a_complete"] == 1]
    elif status_filter == "Form B lengkap":
        filtered = filtered[filtered["form_b_complete"] == 1]
    elif status_filter == "Analysis-ready":
        filtered = filtered[
            (filtered["first_presentation"] == 1)
            & (filtered["form_a_complete"] == 1)
            & (filtered["form_b_complete"] == 1)
        ]

    display_columns = [
        "id_studi", "contact_date", "site", "unit", "rf_n_missing", "rf_score",
        "predictor_window_violation", "outcome_complete", "outcome24", "transfer24", "form_b_complete",
    ]
    display = filtered[display_columns].copy()
    display["site"] = display["site"].map(SITE_LABELS)
    st.dataframe(display, width="stretch", hide_index=True)

    st.subheader("Unduh")
    stamp = date.today().isoformat()
    analysis_ready = frame[
        (frame["first_presentation"] == 1)
        & (frame["form_a_complete"] == 1)
        & (frame["form_b_complete"] == 1)
    ]
    dictionary = pd.DataFrame(DATA_DICTIONARY)
    missingness = pd.DataFrame(
        {
            "variable": frame.columns,
            "n_missing": frame.isna().sum().values,
            "percent_missing": (frame.isna().mean().values * 100).round(1),
        }
    )
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Unduh seluruh data CSV",
            frame.to_csv(index=False, na_rep=""),
            file_name=f"triage_all_{stamp}.csv",
            mime="text/csv",
            width="stretch",
        )
        st.download_button(
            "Unduh analysis-ready CSV",
            analysis_ready.to_csv(index=False, na_rep=""),
            file_name=f"triage_analysis_ready_{stamp}.csv",
            mime="text/csv",
            width="stretch",
        )
    with c2:
        st.download_button(
            "Unduh kamus variabel CSV",
            dictionary.to_csv(index=False),
            file_name="triage_data_dictionary.csv",
            mime="text/csv",
            width="stretch",
        )
        st.download_button(
            "Unduh ringkasan missingness CSV",
            missingness.to_csv(index=False),
            file_name=f"triage_missingness_{stamp}.csv",
            mime="text/csv",
            width="stretch",
        )
    st.caption(
        "Kolom kosong pada CSV dibaca sebagai NA di R. Ekspor seluruh data dipertahankan untuk audit trail; ekspor analysis-ready hanya memilih episode eligible dengan Form A dan B lengkap."
    )


def render_instructions() -> None:
    st.title("Petunjuk Penggunaan")
    st.markdown(
        """
### Alur kerja

1. Beri setiap episode **ID studi pseudonim**. Jangan masukkan nama, nomor rekam medis, nomor telepon, atau alamat pasien.
2. Isi Form A pada kontak pertama dan sebelum hasil penunjang atau keputusan disposisi.
3. Tim penelitian mengisi Form B setelah penelusuran luaran. Untuk pasien transfer, konfirmasi kejadian sampai fasilitas penerima.
4. Buka Rekap dan Ekspor untuk mengunduh CSV serta kamus variabel.

### Aturan data penting

- Domain yang tidak dapat dinilai disimpan kosong sebagai `NA`; aplikasi tidak memakai kode 9.
- `map`, `rf_n_missing`, `rf_score`, `rf_airway_override`, `outcome24_raw`, dan `outcome24` dihitung otomatis.
- `rf_score` hanya tersedia bila semua enam domain lengkap.
- Site disimpan sebagai strata evaluasi, bukan komponen skor.
- Transfer sendiri bukan luaran primer. Luaran primer memerlukan sedikitnya satu kejadian high-acuity terkonfirmasi.
- Bila follow-up tidak lengkap dan tidak ada event terkonfirmasi, `outcome24` tetap `NA`, bukan 0.

### Penyimpanan dan deployment

- SQLite cocok untuk uji lokal. Pada Streamlit Community Cloud, gunakan PostgreSQL melalui `DATABASE_URL` karena file lokal tidak dijamin persisten.
- Atur `APP_PASSWORD` atau `APP_PASSWORD_SHA256` di Streamlit Secrets sebelum membagikan aplikasi.
- Gunakan akses privat dan layanan basis data yang disetujui institusi/komite etik. Aplikasi ini tidak menggantikan kebijakan keamanan data rumah sakit.
"""
    )
    st.code(
        'dat <- readr::read_csv("triage_analysis_ready_YYYY-MM-DD.csv", na = c("", "NA"))\n'
        'domain <- c("rf_systemic", "rf_trismus", "rf_swallow", "rf_airway", "rf_spread", "rf_host")\n'
        'stopifnot(all(vapply(dat[domain], function(x) all(is.na(x) | x %in% c(0, 1)), logical(1))))',
        language="r",
    )


if page == "Form A":
    render_form_a()
elif page == "Form B":
    render_form_b()
elif page == "Rekap dan ekspor":
    render_recap()
else:
    render_instructions()
