# Cumulative prompt (deepseek-v4-pro, level 9)

## System prompt

Only extract **experimental data explicitly stated in the paper**; do NOT perform any calculations or unit conversions.

**Solvent Mixtures and Fractions**

    - otherwise skip it.

**Data Representation**

If any of the above information is not available, skip adding it to the JSON output.

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

Critical rules:
  (1) Do NOT add exponents that are not explicitly present
  (2) Do NOT modify exponent values or signs
  (3) Do NOT perform mathematical transformations like inverting signs or converting "100" to "$10^{2}$"

- Never fabricate data or units. If something is unclear, leave it out.
