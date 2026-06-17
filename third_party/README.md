# third_party/bigmixsoldb

This folder vendors the published **BigMixSolDB** scoring matcher, which this thesis
reuses for its primary row-level F1 metric instead of reimplementing it.

- **Source:** BigChemistry-RobotLab/BigMixSolDB, `src/bigmixsoldb/`
- **Authors:** Voinea, A., Thoeni, A. C. M., Veenman, E., Huck, W. T. S., Kachman, T., and Mabesoone, M. F. J. (2026). BigMixSolDB. ChemRxiv. https://doi.org/10.26434/chemrxiv.15001616/v1
- **Licence:** GNU AGPL v3 (see `LICENSE`).

## What is included

Only the modules the matcher needs are vendored: `compare.py` (the matcher),
`postprocess.py`, `molecules.py`, `constants.py`, `files.py`, `yaml_utils.py`,
`__init__.py`, and `data/name_to_smiles.json` (the curated name-to-SMILES table).
The training, parsing, and lookup modules of the full package are not included.

## The one change

`compare.py` is the published file unchanged except for a small additive Pressure
extension: pressure is added to the record and to the exact-match key, because the
published matcher ignores pressure while this thesis's ablations turn on it. Every
changed line is marked `# PATCH (Pijl):` (or `added`). The matching algorithm,
molecule identity, name handling, and unit normalisation are untouched.

The thesis scorer (`../matcher.py`) keeps its own JSON parsing and row flattening
and then calls this matcher to count exact and partial matches.
