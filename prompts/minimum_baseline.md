# Minimum prompt

The smallest prompt: a one-line task instruction plus the JSON schema
skeleton, nothing else.

## System prompt

Extract the solubility data from the chemistry paper markdown below.

Output as a JSON array matching this schema:
```
[
  {
    "compound": "<primary name>",
    "synonyms": "<synonym1|synonym2|...>" or null,
    "measurements": [
      {
        "solvent_system": [
          {"order": 1, "name": "<solvent 1>", "synonyms": "<...>" or null}
        ],
        "units": {
          "concentration_1": "<unit>",
          "concentration_2": "<unit>",
          "solubility": "<unit>",
          "temperature": "<unit>",
          "pressure": "<unit>"
        },
        "columns": ["concentration_1", "concentration_2", "solubility", "temperature", "pressure"],
        "data": [
          [<value or null>, <value or null>, <value or null>, <value or null>, <value or null>]
        ]
      }
    ]
  }
]
```
