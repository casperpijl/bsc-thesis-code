"""Scoring code for the experiment.

It reads the model's JSON answer and turns it into rows (parse_response + flatten),
then scores those rows against the correct answers.

The primary row-level F1 is done by the published BigMixSolDB matcher, which lives
in third_party/bigmixsoldb/. We do not reimplement the matching: we put our rows in
the format that matcher reads, call it, and read back how many rows matched. The
parsing and flattening of the model answer is our own code.
"""

import json
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
VLM_DIR = Path("set_extractions_vlm")

# the vendored published matcher
sys.path.insert(0, str(HERE / "third_party"))
from bigmixsoldb.compare import compare_csv_files, normalize_doi
from bigmixsoldb.molecules import load_name_to_smiles_map

NAME_MAP_PATH = HERE / "third_party" / "bigmixsoldb" / "data" / "name_to_smiles.json"


# Reading the model answer into flat rows (our own code)

# A unit sometimes carries a power-of-ten scale, like "10^4 x", which means the
# mole fraction values were multiplied by 10000. These patterns find that scale
# so we can divide it back out of the values.
SCALED_MOLE_FRACTION_RE = re.compile(
    r"10\s*\^\s*\{?\s*(-?\d+)\s*\}?\s*(?:\\cdot|·)?\s*x",
    re.IGNORECASE,
)

MOLE_FRACTION_FACTOR_RE = re.compile(
    r"(?:^|[^0-9])(10+)\s*(?:\\cdot|·)?\s*x(?:$|[^a-z0-9])",
    re.IGNORECASE,
)

MASS_FRACTION_FACTOR_RE = re.compile(
    r"(?:^|[^0-9])(10+)\s*(?:\\,?|\\cdot|·)?\s*w(?:$|[^a-z0-9])",
    re.IGNORECASE,
)

# things like "mol %", "wt%", "vol%"
PERCENT_RE = re.compile(r"\b(mol|wt|mass|vol)\s*%", re.IGNORECASE)

# a number written in LaTeX, like "1.2 \times 10^{-3}"
LATEX_SCI_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*\\+times\s*10\s*\^\s*\{?\s*(-?\d+)\s*\}?",
)


def latex_to_number(val):
    """Try to read a LaTeX style number as a normal number, or give back None."""
    if not isinstance(val, str):
        return None
    s = val.replace("$", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    m = LATEX_SCI_RE.match(s)
    if m and m.end() == len(s):
        try:
            return float(f"{m.group(1)}e{m.group(2)}")
        except ValueError:
            return None
    return None


FRACTION_MAP = {
    "mole fraction": "mole fraction",
    "x": "mole fraction",
    "mole fraction solubility": "mole fraction",
    "mass fraction": "mass fraction",
    "w": "mass fraction",
    "volume fraction": "volume fraction",
    "v": "volume fraction",
    "φ": "volume fraction",
    "phi": "volume fraction",
}

TEMPERATURE_UNITS = {
    "k": ("K", 1.0, 0.0),
    "kelvin": ("K", 1.0, 0.0),
    "c": ("K", 1.0, 273.15),
    "°c": ("K", 1.0, 273.15),
    "celsius": ("K", 1.0, 273.15),
}

PRESSURE_UNITS = {
    "pa": 1.0,
    "kpa": 1e3,
    "mpa": 1e6,
    "bar": 1e5,
    "atm": 101325.0,
    "psi": 6894.76,
}


def fix_unit_chars(s):
    if s is None:
        return ""
    s = s.replace("Â·", "·")
    s = s.replace("�", "·")
    return s


def clean_unit(s):
    if s is None:
        return ""
    s = fix_unit_chars(s)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("$", "").strip().lower()
    return s


def normalize_unit(raw):
    """Work out the base unit, a multiplier and an offset for a unit string."""
    if raw is None:
        return ("", 1.0, 0.0)
    s = clean_unit(raw)
    if s == "":
        return ("", 1.0, 0.0)

    # some units scale the value by a power of ten, so we divide that scaling back out
    m = SCALED_MOLE_FRACTION_RE.search(s)
    if m:
        n = int(m.group(1))
        return ("mole fraction", 10.0 ** (-n), 0.0)

    m = MOLE_FRACTION_FACTOR_RE.search(s)
    if m:
        n = len(m.group(1)) - 1
        return ("mole fraction", 10.0 ** (-n), 0.0)

    m = MASS_FRACTION_FACTOR_RE.search(s)
    if m:
        n = len(m.group(1)) - 1
        return ("mass fraction", 10.0 ** (-n), 0.0)

    m = PERCENT_RE.search(s)
    if m:
        prefix = m.group(1).lower()
        base_by_prefix = {
            "mol": "mole fraction",
            "wt": "mass fraction",
            "mass": "mass fraction",
            "vol": "volume fraction",
        }
        return (base_by_prefix[prefix], 0.01, 0.0)

    if s in FRACTION_MAP:
        return (FRACTION_MAP[s], 1.0, 0.0)

    if s in TEMPERATURE_UNITS:
        return TEMPERATURE_UNITS[s]

    if s in PRESSURE_UNITS:
        return ("Pa", PRESSURE_UNITS[s], 0.0)

    print("unknown unit:", raw)
    return (raw, 1.0, 0.0)


FLAT_COLUMNS = [
    "Compound Name",
    "Solvent 1", "Solvent 2",
    "Concentration Solvent 1", "Concentration Solvent 2", "Concentration Unit",
    "Solubility", "Solubility Unit",
    "Temperature", "Temperature Unit",
    "Pressure", "Pressure Unit",
]


def empty_row():
    return {col: None for col in FLAT_COLUMNS}


def is_number(x):
    """True for a real int or float, but not for True/False."""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def apply_unit(value, unit):
    """Scale one cell value by its unit and give back a float, or None if the
    value is not a number we can read. unit is the (base, multiplier, offset)
    tuple that normalize_unit returns."""
    base, mult, offset = unit
    if is_number(value):
        return value * mult + offset
    # the value might be a LaTeX string like "1.2 \times 10^{-3}"
    number = latex_to_number(value)
    if number is None:
        return None
    return number * mult + offset


def fill_missing_concentration(flat):
    """For a two-solvent row, if only one fraction is given, the other is 1 minus it."""
    if flat.get("Solvent 2") is None:
        return flat
    c1 = flat.get("Concentration Solvent 1")
    c2 = flat.get("Concentration Solvent 2")
    if is_number(c1) and not is_number(c2):
        flat["Concentration Solvent 2"] = 1 - c1
    elif is_number(c2) and not is_number(c1):
        flat["Concentration Solvent 1"] = 1 - c2
    return flat


def fix_pure_solvent(flat):
    """If a "mixture" is really one pure solvent (the other has fraction 0 or 1),
    turn it back into a single-solvent row."""
    if flat["Solvent 2"] is None:
        return flat
    c1 = flat["Concentration Solvent 1"]
    if c1 == 0.0:
        flat["Solvent 1"] = flat["Solvent 2"]
        flat["Solvent 2"] = None
        flat["Concentration Solvent 1"] = None
        flat["Concentration Solvent 2"] = None
        flat["Concentration Unit"] = None
    elif c1 == 1.0:
        flat["Solvent 2"] = None
        flat["Concentration Solvent 1"] = None
        flat["Concentration Solvent 2"] = None
        flat["Concentration Unit"] = None
    return flat


def flatten(nested):
    """Turn the nested JSON answer into one flat row per data point."""
    if isinstance(nested, dict):
        nested = [nested]
    out = []
    for compound in nested:
        comp_name = compound.get("compound")
        for m in compound.get("measurements", []):
            solvents = m.get("solvent_system", [])
            units = m.get("units", {})
            columns = m.get("columns", [])
            data = m.get("data", [])
            s1 = solvents[0]["name"] if len(solvents) >= 1 else None
            s2 = solvents[1]["name"] if len(solvents) >= 2 else None

            # work out the (base unit, multiplier, offset) for each column once
            col_units = {}
            for col in columns:
                raw = units.get(col)
                col_units[col] = normalize_unit(raw) if raw is not None else (None, 1.0, 0.0)

            for row in data:
                flat = empty_row()
                flat["Compound Name"] = comp_name
                flat["Solvent 1"] = s1
                flat["Solvent 2"] = s2
                for i, col in enumerate(columns):
                    base = col_units[col][0]
                    scaled = apply_unit(row[i], col_units[col])
                    if col == "concentration_1":
                        flat["Concentration Solvent 1"] = scaled
                        flat["Concentration Unit"] = flat["Concentration Unit"] or base
                    elif col == "concentration_2":
                        flat["Concentration Solvent 2"] = scaled
                        flat["Concentration Unit"] = flat["Concentration Unit"] or base
                    elif col == "solubility":
                        flat["Solubility"] = scaled
                        flat["Solubility Unit"] = base
                    elif col == "temperature":
                        flat["Temperature"] = scaled
                        flat["Temperature Unit"] = base
                    elif col == "pressure":
                        flat["Pressure"] = scaled
                        flat["Pressure Unit"] = base
                out.append(fix_pure_solvent(fill_missing_concentration(flat)))
    return out


FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def find_json_block(s):
    # find the longest [...] or {...} block in the text, in case the model
    # wrapped the JSON in some extra words
    best = None
    for open_c, close_c in (("[", "]"), ("{", "}")):
        depth = 0
        start = None
        for i, c in enumerate(s):
            if c == open_c:
                if depth == 0:
                    start = i
                depth += 1
            elif c == close_c and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    block = s[start:i+1]
                    if best is None or len(block) > len(best):
                        best = block
                    start = None
    return best


def parse_response(raw):
    """Try to read the answer as JSON, with a few extra tries if it is messy."""
    out = {"valid_strict": False, "valid_recovered": False, "data": None}
    try:
        out["data"] = json.loads(raw)
        out["valid_strict"] = True
        return out
    except json.JSONDecodeError:
        pass

    m = FENCE_RE.search(raw)
    fence_inner = m.group(1) if m else None
    if fence_inner is not None:
        try:
            out["data"] = json.loads(fence_inner)
            out["valid_recovered"] = True
            return out
        except json.JSONDecodeError:
            pass

    block = find_json_block(raw)
    if block is not None:
        try:
            out["data"] = json.loads(block)
            out["valid_recovered"] = True
            return out
        except json.JSONDecodeError:
            pass

    candidate = fence_inner or block or raw
    rewritten = LATEX_SCI_RE.sub(
        lambda mm: f"{mm.group(1)}e{mm.group(2)}", candidate
    )
    if rewritten != candidate:
        try:
            out["data"] = json.loads(rewritten)
            out["valid_recovered"] = True
            return out
        except json.JSONDecodeError:
            pass

    return out


# Scoring with the published BigMixSolDB matcher (third_party/bigmixsoldb)

# columns the matcher reads on the predicted side
PRED_COLUMNS = [
    "doi", "Compound Name", "SMILES_Compound",
    "Solvent 1", "SMILES_Solvent_1", "Solvent 2", "SMILES_Solvent_2",
    "Concentration Solvent 1", "Concentration Unit",
    "Solubility", "Solubility Unit", "Temperature", "Pressure",
]

# the four value fields the matcher can report a per-field difference on
VALUE_FIELDS = ["temperature", "solubility", "composition", "pressure"]


def simple_name(s):
    """Lower-case and tidy a chemical name so it can be looked up."""
    if s is None:
        return None
    s = str(s).strip().lower()
    if s in ("", "-", "none", "nan", "n/a"):
        return None
    return " ".join(s.split())


def build_name_to_smiles():
    """Build a dict from chemical name to SMILES, using the matcher's table plus the names in the reference CSVs."""
    mapping = {}
    for name, smiles in load_name_to_smiles_map(NAME_MAP_PATH).items():
        key = simple_name(name)
        if key and smiles:
            mapping[key] = str(smiles)
    for ref in VLM_DIR.glob("*_ref.csv"):
        df = pd.read_csv(ref).replace("-", None)
        for _, r in df.iterrows():
            for name_col, smiles_col in (
                ("Compound Name", "SMILES_Compound"),
                ("Solvent 1", "SMILES_Solvent_1"),
                ("Solvent 2", "SMILES_Solvent_2"),
            ):
                name = r.get(name_col)
                smiles = r.get(smiles_col)
                if pd.isna(name) or pd.isna(smiles):
                    continue
                key = simple_name(name)
                if key:
                    mapping[key] = str(smiles)
    return mapping


NAME_TO_SMILES = build_name_to_smiles()

# two scratch files the matcher reads (overwritten on every call)
TMP_DIR = Path(tempfile.mkdtemp(prefix="rl_score_"))
PRED_TMP = TMP_DIR / "predicted.csv"
REF_TMP = TMP_DIR / "reference.csv"


def load_ref_csv(doi):
    """Read the paper's reference rows. Only used to count the ground-truth rows."""
    df = pd.read_csv(VLM_DIR / f"{doi}_ref.csv").replace("-", None)
    return df.to_dict("records")


def write_predicted_csv(llm_flat, doi):
    """Write our flat rows in the format the matcher reads, with SMILES attached."""
    rows = []
    for fr in llm_flat:
        rows.append({
            "doi": doi,
            "Compound Name": fr.get("Compound Name"),
            "SMILES_Compound": NAME_TO_SMILES.get(simple_name(fr.get("Compound Name"))),
            "Solvent 1": fr.get("Solvent 1"),
            "SMILES_Solvent_1": NAME_TO_SMILES.get(simple_name(fr.get("Solvent 1"))),
            "Solvent 2": fr.get("Solvent 2"),
            "SMILES_Solvent_2": NAME_TO_SMILES.get(simple_name(fr.get("Solvent 2"))),
            "Concentration Solvent 1": fr.get("Concentration Solvent 1"),
            "Concentration Unit": fr.get("Concentration Unit"),
            "Solubility": fr.get("Solubility"),
            "Solubility Unit": fr.get("Solubility Unit"),
            "Temperature": fr.get("Temperature"),
            "Pressure": fr.get("Pressure"),
        })
    # always write the header so the matcher reads zero rows instead of failing
    pd.DataFrame(rows, columns=PRED_COLUMNS).to_csv(PRED_TMP, index=False)


def write_reference_csv(doi):
    """The reference is the paper's _ref.csv, with a doi column added."""
    df = pd.read_csv(VLM_DIR / f"{doi}_ref.csv")
    df["doi"] = doi
    df.to_csv(REF_TMP, index=False)


def f1(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": score}


def score_paper(llm_flat, doi):
    """Score one paper against its reference with the BigMixSolDB matcher and return row-level F1 plus per-field scores."""
    write_predicted_csv(llm_flat, doi)
    write_reference_csv(doi)
    report = compare_csv_files(PRED_TMP, REF_TMP, reference_format="standardized")
    rep = report.get("doi_reports", {}).get(normalize_doi(doi))
    if rep is None:
        n_ref = len(load_ref_csv(doi))
        return {"row_level": f1(0, 0, n_ref), "unmatched_row_rate": 0.0, "per_field": {}}

    exact = rep["exact_matches"]
    partial = rep["partial_matches"]
    extra = rep["input_only_count"]
    missing = rep["reference_only_count"]

    row_level = f1(exact, extra + partial, missing + partial)

    aligned = exact + partial + extra
    unmatched_row_rate = extra / aligned if aligned else 0.0

    # Per-field score: among the rows matched on chemistry (exact + partial), how
    # often does each value field agree? Every exact pair agrees on every field. For
    # a partial pair the matcher lists the fields that differ, so a field agrees when
    # it is not in that list.
    matched = exact + partial
    per_field = {}
    if matched:
        for field in VALUE_FIELDS:
            agree = exact
            for diff in rep.get("row_wise_differences", []):
                if field not in diff.get("differences", {}):
                    agree += 1
            per_field[field] = agree / matched

    return {"row_level": row_level,
            "unmatched_row_rate": unmatched_row_rate,
            "per_field": per_field}
