# Research Dataset Manifest

`reports/research_dataset_manifest.json` is the machine-readable identity of the
research dataset used by the daily pipeline. It contains metadata and SHA-256 hashes,
not market-data payloads.

## Build And Validate

Run after daily feature computation and deferred reconciliation:

```bash
python -m src.cli build-research-manifest
python -m src.cli validate-research-manifest
```

The GitHub daily workflow builds the manifest after the deferred collector and before
the static Vercel export. A build fails closed when a required artifact is missing,
unreadable, outside the repository, or inconsistent with the feature contract.

## Identity Contract

Manifest schema `2` records:

- full Git source revision;
- deterministic dataset ID derived from the manifest content;
- feature-contract version, generator, canonical inputs, and exact output-column order;
- path, role, format, SHA-256, byte size, and tabular schema for each artifact;
- row, ticker, and date coverage where those dimensions exist;
- explicit safety flags.

The required artifact set covers canonical and adjusted prices, the feature matrix,
current and historical point-in-time universes, corporate actions, verified price
events, deferred reconciliation cache/report/details, and incident dispositions.

CSV and JSON fingerprints use canonical UTF-8 bytes with LF line endings; Parquet uses
its binary bytes. This keeps SHA-256, byte size, and dataset identity stable across Git
checkouts on Linux and Windows without ignoring any logical text change.

`eod-technical-v1` declares 49 feature-matrix columns. Adding, removing, or
reordering a column without updating the versioned contract blocks manifest generation.

## Reproduction

To reproduce a recorded result:

1. check out `source_revision`;
2. restore every artifact at its recorded path;
3. verify every recorded SHA-256;
4. run `validate-research-manifest`;
5. compare `dataset_id` and `feature_contract.sha256` with the model/report evidence.

The manifest remains research metadata. It never changes
`final_execution_eligible=false`, does not authorize model promotion, and does not
authorize broker execution.
