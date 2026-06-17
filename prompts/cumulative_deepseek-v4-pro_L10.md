# Cumulative prompt (deepseek-v4-pro, level 10)

## System prompt

Only extract **experimental data explicitly stated in the paper**; do NOT perform any calculations or unit conversions.

**Solvent Mixtures and Fractions**

    - otherwise skip it.

**Data Representation**

If any of the above information is not available, skip adding it to the JSON output.

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
