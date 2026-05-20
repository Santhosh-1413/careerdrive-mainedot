"""OPM Occupational Series codes and USAJobs search parameter builder."""

OPM_SERIES = {
    "civil engineer":            ["0810"],
    "transportation engineer":   ["0810"],
    "highway engineer":          ["0810"],
    "traffic engineer":          ["2130"],
    "transportation operations": ["2150"],
    "rail inspector":            ["2150"],
    "railroad inspector":        ["2150"],
    "locomotive engineer":       ["2150"],
    "air traffic controller":    ["2152"],
    "aviation":                  ["2152","1825"],
    "gis specialist":            ["1370"],
    "cartographer":              ["1370"],
    "urban planner":             ["0020"],
    "transit planner":           ["2101"],
    "transportation planner":    ["2101"],
    "systems engineer":          ["0801"],
    "smart mobility":            ["0801","0855"],
    "data analyst":              ["1101","0343"],
    "logistics":                 ["2003","0346"],
    "supply chain":              ["2003"],
    "project manager":           ["0340"],
    "program manager":           ["0340"],
    "policy analyst":            ["0301"],
}

DOMAIN_SERIES = {
    "railways":       ["2150","2130","0855","0830"],
    "highways":       ["0810","0809","0819"],
    "aviation":       ["2152","2151","2181","1825"],
    "public_transit": ["2101","0020","0340"],
    "maritime":       ["2161","2030"],
    "logistics":      ["2003","0346","2001"],
    "urban_planning": ["1370","0801","1550","0020"],
}

US_STATES = {
    "alabama":"Alabama","alaska":"Alaska","arizona":"Arizona","arkansas":"Arkansas",
    "california":"California","colorado":"Colorado","connecticut":"Connecticut",
    "delaware":"Delaware","florida":"Florida","georgia":"Georgia","hawaii":"Hawaii",
    "idaho":"Idaho","illinois":"Illinois","indiana":"Indiana","iowa":"Iowa",
    "kansas":"Kansas","kentucky":"Kentucky","louisiana":"Louisiana","maine":"Maine",
    "maryland":"Maryland","massachusetts":"Massachusetts","michigan":"Michigan",
    "minnesota":"Minnesota","mississippi":"Mississippi","missouri":"Missouri",
    "montana":"Montana","nebraska":"Nebraska","nevada":"Nevada",
    "new hampshire":"New Hampshire","new jersey":"New Jersey","new mexico":"New Mexico",
    "new york":"New York","north carolina":"North Carolina","north dakota":"North Dakota",
    "ohio":"Ohio","oklahoma":"Oklahoma","oregon":"Oregon","pennsylvania":"Pennsylvania",
    "rhode island":"Rhode Island","south carolina":"South Carolina",
    "south dakota":"South Dakota","tennessee":"Tennessee","texas":"Texas","utah":"Utah",
    "vermont":"Vermont","virginia":"Virginia","washington":"Washington",
    "west virginia":"West Virginia","wisconsin":"Wisconsin","wyoming":"Wyoming",
    "district of columbia":"District of Columbia",
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
    "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas",
    "KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts",
    "MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana",
    "NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico",
    "NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma",
    "OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina",
    "SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont",
    "VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming",
    "DC":"District of Columbia",
}


def get_series_for_role(role: str) -> list[str]:
    role_lower = role.lower()
    for key, codes in OPM_SERIES.items():
        if key in role_lower or role_lower in key:
            return codes
    return []


def get_series_for_domain(domain: str) -> list[str]:
    return DOMAIN_SERIES.get(domain.lower(), [])


def build_usajobs_params(
    role: str = "",
    domain: str = "",
    location: str = "",
    keywords: str = "",
    results_per_page: int = 8,
    remote_only: bool = False,
    full_fields: bool = True,
    hiring_path: str = "public",
    min_salary: int = 0,
) -> dict:
    params = {
        "ResultsPerPage": min(results_per_page, 25),
        "SortField": "OpenDate",
        "SortDirection": "Desc",
        "WhoMayApply": hiring_path,
        "Fields": "Full" if full_fields else "Min",
        "DatePosted": 60,
    }

    # Series codes — default to broad transport series if nothing specified
    series = get_series_for_role(role) if role else []
    if not series and domain:
        series = get_series_for_domain(domain)
    if not series:
        # Default: core transportation OPM series covering all 7 sub-domains
        series = ["0810", "2101", "2150", "0020", "1370", "2003", "2130"]
    if series:
        params["JobCategoryCode"] = ";".join(series[:4])

    # Title search
    if role:
        params["PositionTitle"] = role

    # Keywords (supplementary)
    if keywords and keywords.lower() != role.lower():
        params["Keyword"] = keywords

    # Salary
    if min_salary > 0:
        params["RemunerationMinimumAmount"] = min_salary

    # Remote / location
    if remote_only:
        params["RemoteIndicator"] = "True"
    elif location:
        loc = location.strip().lower()
        if loc not in ("remote","anywhere","usa","us",""):
            state_name = US_STATES.get(location.strip()) or US_STATES.get(loc.title())
            params["LocationName"] = state_name or location

    return params
