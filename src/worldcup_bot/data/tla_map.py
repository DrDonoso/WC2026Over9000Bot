"""TLA (Three-Letter Abbreviation) to ISO 3166-1 alpha-2 mapping.

Covers the 48 WC2026 nations plus legacy Euro 2024 entries.
Used by the `flag` library to render country flag emojis.
"""

from __future__ import annotations

TLA_TO_ISO: dict[str, str] = {
    # ── UEFA ──────────────────────────────────────────────────────────────────
    "ALB": "AL",    # Albania
    "AND": "AD",    # Andorra
    "AUT": "AT",    # Austria
    "BEL": "BE",    # Belgium
    "BIH": "BA",    # Bosnia and Herzegovina
    "BUL": "BG",    # Bulgaria
    "CRO": "HR",    # Croatia
    "CYP": "CY",    # Cyprus
    "CZE": "CZ",    # Czech Republic
    "DEN": "DK",    # Denmark
    "ENG": "GBENG", # England
    "ESP": "ES",    # Spain
    "FIN": "FI",    # Finland
    "FRA": "FR",    # France
    "GEO": "GE",    # Georgia
    "GER": "DE",    # Germany
    "GRE": "GR",    # Greece
    "HUN": "HU",    # Hungary
    "ISL": "IS",    # Iceland
    "ITA": "IT",    # Italy
    "KVX": "XK",    # Kosovo (unofficial ISO)
    "LIE": "LI",    # Liechtenstein
    "LTU": "LT",    # Lithuania
    "LUX": "LU",    # Luxembourg
    "MDA": "MD",    # Moldova
    "MKD": "MK",    # North Macedonia
    "MLT": "MT",    # Malta
    "MNE": "ME",    # Montenegro
    "NED": "NL",    # Netherlands
    "NIR": "GBNIR", # Northern Ireland
    "NOR": "NO",    # Norway
    "POL": "PL",    # Poland
    "POR": "PT",    # Portugal
    "ROU": "RO",    # Romania
    "RUS": "RU",    # Russia
    "SCO": "GBSCT", # Scotland
    "SRB": "RS",    # Serbia
    "SUI": "CH",    # Switzerland
    "SVK": "SK",    # Slovakia
    "SVN": "SI",    # Slovenia
    "SWE": "SE",    # Sweden
    "TUR": "TR",    # Turkey
    "UKR": "UA",    # Ukraine
    "WAL": "GBWLS", # Wales
    "AZE": "AZ",    # Azerbaijan
    "ARM": "AM",    # Armenia
    # ── CONMEBOL ─────────────────────────────────────────────────────────────
    "ARG": "AR",    # Argentina
    "BOL": "BO",    # Bolivia
    "BRA": "BR",    # Brazil
    "CHI": "CL",    # Chile (FIFA/CONMEBOL code)
    "CHL": "CL",    # Chile (ISO 3166-1 alpha-3 alias)
    "COL": "CO",    # Colombia
    "ECU": "EC",    # Ecuador
    "PAR": "PY",    # Paraguay (FIFA/CONMEBOL code)
    "PRY": "PY",    # Paraguay (ISO 3166-1 alpha-3 alias)
    "PER": "PE",    # Peru
    "URU": "UY",    # Uruguay (traditional FIFA code)
    "URY": "UY",    # Uruguay (football-data.org API code)
    "VEN": "VE",    # Venezuela
    # ── CONCACAF ─────────────────────────────────────────────────────────────
    "CAN": "CA",    # Canada
    "CRC": "CR",    # Costa Rica
    "CUB": "CU",    # Cuba
    "CUW": "CW",    # Curaçao
    "GUA": "GT",    # Guatemala
    "HAI": "HT",    # Haiti
    "HON": "HN",    # Honduras
    "JAM": "JM",    # Jamaica
    "MEX": "MX",    # Mexico
    "PAN": "PA",    # Panama
    "SLV": "SV",    # El Salvador
    "TRI": "TT",    # Trinidad and Tobago
    "USA": "US",    # United States
    # ── AFC ──────────────────────────────────────────────────────────────────
    "AUS": "AU",    # Australia
    "BHR": "BH",    # Bahrain
    "CHN": "CN",    # China
    "IDN": "ID",    # Indonesia
    "IND": "IN",    # India
    "IRN": "IR",    # Iran
    "IRQ": "IQ",    # Iraq
    "JOR": "JO",    # Jordan
    "JPN": "JP",    # Japan
    "KOR": "KR",    # South Korea
    "KSA": "SA",    # Saudi Arabia (FIFA/AFC code)
    "SAU": "SA",    # Saudi Arabia (ISO 3166-1 alpha-3 / football-data.org alias)
    "KUW": "KW",    # Kuwait
    "LBN": "LB",    # Lebanon
    "MYS": "MY",    # Malaysia
    "OMN": "OM",    # Oman
    "PHI": "PH",    # Philippines
    "QAT": "QA",    # Qatar
    "SYR": "SY",    # Syria
    "THA": "TH",    # Thailand
    "UZB": "UZ",    # Uzbekistan
    "VIE": "VN",    # Vietnam
    # ── CAF ──────────────────────────────────────────────────────────────────
    "ALG": "DZ",    # Algeria
    "ANG": "AO",    # Angola
    "BEN": "BJ",    # Benin
    "BFA": "BF",    # Burkina Faso
    "CMR": "CM",    # Cameroon
    "CGO": "CG",    # Congo
    "CIV": "CI",    # Côte d'Ivoire
    "COD": "CD",    # DR Congo
    "CPV": "CV",    # Cape Verde
    "EGY": "EG",    # Egypt
    "ETH": "ET",    # Ethiopia
    "GAB": "GA",    # Gabon
    "GAM": "GM",    # Gambia
    "GHA": "GH",    # Ghana
    "GUI": "GN",    # Guinea
    "KEN": "KE",    # Kenya
    "LBA": "LY",    # Libya
    "MAD": "MG",    # Madagascar
    "MAR": "MA",    # Morocco
    "MLI": "ML",    # Mali
    "MOZ": "MZ",    # Mozambique
    "MRI": "MU",    # Mauritius
    "MTN": "MR",    # Mauritania
    "NGA": "NG",    # Nigeria
    "RSA": "ZA",    # South Africa
    "RWA": "RW",    # Rwanda
    "SEN": "SN",    # Senegal
    "SLE": "SL",    # Sierra Leone
    "SOM": "SO",    # Somalia
    "SSD": "SS",    # South Sudan
    "TAN": "TZ",    # Tanzania
    "TUN": "TN",    # Tunisia
    "UGA": "UG",    # Uganda
    "ZAM": "ZM",    # Zambia
    "ZIM": "ZW",    # Zimbabwe
    # ── OFC ──────────────────────────────────────────────────────────────────
    "FIJ": "FJ",    # Fiji
    "NCL": "NC",    # New Caledonia
    "NZL": "NZ",    # New Zealand
    "PNG": "PG",    # Papua New Guinea
    "SOL": "SB",    # Solomon Islands
    "VAN": "VU",    # Vanuatu
}


def tla_to_iso(code: str) -> str | None:
    """Return ISO 3166-1 alpha-2 code for a TLA, or None if unknown."""
    if not code or code == "**":
        return None
    return TLA_TO_ISO.get(code.upper())
