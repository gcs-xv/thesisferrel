#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
csv_path <- if (length(args) >= 1) args[[1]] else "triage_analysis_ready.csv"

if (!requireNamespace("readr", quietly = TRUE)) {
  stop("Paket readr belum terpasang. Jalankan install.packages('readr').")
}

dat <- readr::read_csv(
  csv_path,
  na = c("", "NA"),
  show_col_types = FALSE
)

domain_vars <- c(
  "rf_systemic", "rf_trismus", "rf_swallow",
  "rf_airway", "rf_spread", "rf_host"
)

missing_columns <- setdiff(domain_vars, names(dat))
if (length(missing_columns) > 0) {
  stop("Kolom domain tidak ditemukan: ", paste(missing_columns, collapse = ", "))
}

valid_domains <- vapply(
  dat[domain_vars],
  function(x) all(is.na(x) | x %in% c(0, 1)),
  logical(1)
)
if (!all(valid_domains)) {
  stop("Ditemukan kode domain selain 0, 1, atau NA.")
}

dat$site_label <- factor(
  dat$site,
  levels = c(1, 2),
  labels = c("RSGM Unhas", "RSPTN Unhas")
)

dat$outcome24_factor <- factor(
  dat$outcome24,
  levels = c(0, 1),
  labels = c("Tidak", "Ya")
)

if (all(c("sbp", "dbp", "map") %in% names(dat))) {
  expected_map <- round((dat$sbp + 2 * dat$dbp) / 3, 1)
  map_mismatch <- !is.na(dat$map) & abs(dat$map - expected_map) > 0.11
  if (any(map_mismatch, na.rm = TRUE)) {
    warning(sum(map_mismatch, na.rm = TRUE), " baris memiliki MAP yang perlu diperiksa.")
  }
}

message("Data berhasil dibaca: ", nrow(dat), " episode dan ", ncol(dat), " variabel.")
message("Outcome24 NA: ", sum(is.na(dat$outcome24)))

saveRDS(dat, sub("\\.csv$", ".rds", csv_path, ignore.case = TRUE))
