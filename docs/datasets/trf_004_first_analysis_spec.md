# TRF-004 First Analysis Specification (post-acquisition)

Status: analysis specification only. No dataset was acquired, validated, or profiled for this milestone.

This document is a compact analysis plan for the first authorized TRF-004 experiment. It is intentionally narrower than the existing planning documents; it does not replace them.

Intended resource
-----------------

- Selected resource: `BTP - Station-wise accidents & fatalities 2018 to 2020`
- Exact CSV URL: `https://data.opencity.in/dataset/94e986d6-7836-4a8e-aa3f-273bee4ea795/resource/fcc5762c-2739-4c86-93fd-67fa4cca0750/download/aef42379-f1f7-4a3b-94f5-5f344e7120f2.csv`
- Dataset page: `https://data.opencity.in/dataset/bengaluru-road-crashes-data`
- Resource page: `https://data.opencity.in/dataset/bengaluru-road-crashes-data/resource/fcc5762c-2739-4c86-93fd-67fa4cca0750`

Intended analytical grain
--------------------------

- Primary grain: documented station-wise grouping present in the selected file.
- Secondary grain: aggregation to a common period only if the file supports it and the aggregation is explicitly stated.
- Explicit limitation: the file is police-jurisdiction grouping, not incident coordinates or street-level events. No ward-level, coordinate-level, or street-level claims are supported unless a later resource or verified mapping says so.

Analysis stages (run after successful validation and profiling)
-----------------------------------------------------------------

1. Data-quality summary first
   - header verbatim
   - row count, column count
   - missing-value rate per column
   - duplicate rows
   - ragged rows
   - total/subtotal row labels and how they are represented
   - encoding and BOM presence
2. Schema-as-measured table
   - exact header names
   - values seen in the first few rows
   - explicit note that column meanings are documented only by the header, not by an official dictionary
3. Descriptive counts
   - per-zone, per-sub-division, per-station totals as present in the file
   - explicit handling of total/subtotal rows; do not treat them as ordinary station records
4. Documented facets
   - fatal cases, killed people, non-fatal, injured people, total cases, as present in the file
   - keep raw counts separate from any derived rates
5. Geography note
   - state the finest geography the file actually supports and what it does not support
6. Limitations and supportable questions
   - what the file can answer
   - what the file cannot answer without additional evidence

Supportable first questions (only if the real artifact confirms them)
----------------------------------------------------------------------

- Which zones, sub-divisions, or stations have the highest total cases in the file?
- Is fatal/non-fatal distinction present for all rows, or only some?
- Are total/subtotal rows consistent with the station rows beneath them?
- Which columns are sparse or missing in practice?

Not supportable without additional evidence
--------------------------------------------

- Incident locations or coordinates
- Ward-level joins without a verified mapping
- A single continuous station-wise series spanning 2007-2025
- Stable station identifiers suitable as join keys
- Causal or enforcement-impact conclusions

Provenance requirement
----------------------

Every figure in the first analysis must cite:
- dataset ID
- selected resource URL
- dataset page URL
- acquisition timestamp, byte size, SHA-256
- validation state
- profiling state
- intended-use decision that authorized the acquisition

No LLM-generated findings are allowed to appear as if they were measured from the real artifact.
