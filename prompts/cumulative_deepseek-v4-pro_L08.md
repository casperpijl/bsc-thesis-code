# Cumulative prompt (deepseek-v4-pro, level 8)

## System prompt

Follow the order presented in the tables while extracting data. Only extract **experimental data explicitly stated in the paper**; do NOT perform any calculations or unit conversions.

**Solvent Mixtures and Fractions**

    - otherwise skip it. Always prefer mole fraction if available, and only report one type of fraction per solvent,

**Data Representation**

If any of the above information is not available, skip adding it to the JSON output.

If multiple concentration types are present (e.g., both w1 and x1), only report one type consistently. Prefer mole fraction if available.

Example:
```json
[
  {
    "compound": "<primary name>",
    "synonyms": "<synonym1|synonym2>",
    "measurements": [
      {
        "solvent_system": [
          {"order": 1, "name": "<solvent_1>", "synonyms": null},
          {"order": 2, "name": "<solvent_2>", "synonyms": null}
        ],
        "units": {
          "concentration_1": "mole fraction",
          "solubility": "$10^{4} x$",
          "temperature": "K"
        },
        "columns": ["concentration_1", "solubility", "temperature"],
        "data": [
          [0.1, 0.5, 298.15],
          [0.2, 0.8, 298.15],
          [0.3, 1.1, 308.15]
        ]
      }
    ]
  }
]
```

**Notes**
- Omit fields entirely if they are not present for any data point in the group.
- Do NOT make up synonyms if they are not explicitly mentioned.

- Do NOT perform any calculations yourself. That is, do NOT convert units or infer missing values. Report only what is explicitly stated in the paper.
- If only one concentration is provided for a given mixture, do not infer the second concentration. Skip it.
- If the text mentions that experiments were conducted at atmospheric pressure, include `1` as the value in the `pressure` column of `data`, and `"atm"` as the value of `units.pressure` for the corresponding measurement.
- Prefer using full chemical names for compounds and solvents over abbreviations if those are provided in the text.
- Use Greek letters for compound or solvent names if they are part of the name (e.g., α-Tocopherol, β-Cyclodextrin).

- If a table shows two different concentration unit types for the same mixture, choose one to report consistently and discard the other.
- The order of solvent names matters in mixtures. Follow the order as presented in the paper when listing solvents in `solvent_system` (with `order: 1` first) and their corresponding concentrations. If the paper mentions "<solute> in <solvent1> + <solvent2>" and assigns a concentration unit ("x", or "w") explicitly to a solvent, place that solvent first in `solvent_system` (with `order: 1`), followed by the other solvent.

- Always prefer using mole fraction (x) whenever it is available. If other types of fractions (e.g., mass fraction -> w, volume fraction -> v) are given alongside mole fraction, only report mole fraction in `units.concentration_1` / `units.concentration_2`. If mole fraction is not provided, report the other type of fraction instead.

Critical rules:
  (1) Do NOT add exponents that are not explicitly present
  (2) Do NOT modify exponent values or signs
  (3) Do NOT perform mathematical transformations like inverting signs or converting "100" to "$10^{2}$"

- The paper you receive may contain parsing errors from the PDF conversion process. If you encounter any unclear or garbled text for units or values, consider the context carefully before completing the extraction.
- Never fabricate data or units. If something is unclear, leave it out.
