"""TfL publisher aliases. Source: TfL TNDS Operator records and legal names."""
TFL_OPERATOR_ALIASES = {"ARVA": "AVLO", "ALSO": "AVLO", "UNIB": "UNOE", "LIBC": "ELBG"}
TFL_OPERATOR_CODES = {"BE": "BTRI", "LC": "LONC", "LG": "LGEN"}
TFL_OPERATOR_NOCS = frozenset({"AVLO", "MTLN", "ELBG", "LUTD", "LSOV", "LOTR", "LGEN", "LONC", "GAHL", "MBGA", "METR", "BTRI", "DLBU", "ABLO", "FLON", "UNOE", "SULV", "FALC", "WNGS"})


def operator_noc(national_code, internal_code):
    return TFL_OPERATOR_CODES.get(internal_code) or TFL_OPERATOR_ALIASES.get(national_code, national_code)
