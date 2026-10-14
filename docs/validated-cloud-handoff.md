# Validated cloud handoff: design case study

This generalized case study describes a September–October 2026 workflow for
turning reviewed entity matches into validated import artifacts. It documents
the engineering pattern; production workers, deployment configuration, source
records, SQL mappings, and cloud resource identifiers are not included.

## Problem

A reviewed match file must stay tied to its supplier batch. Repeated delivery,
changed inputs during a query, and an incomplete output workbook can otherwise
produce duplicate processing or misleading completion signals.

## Processing contract

1. Accept only reviewed rows with final company references. Holds and
   creation-needed rows remain in the review workflow.
2. Select the supplier batch using the date carried by the input, rather than
   the day someone reviewed it. Bind queries to exact input objects.
3. Identify the input by content hash and track the object version or ETag.
   Completed duplicates can be skipped; changed content creates a new run.
4. Require output counts and case-to-company mappings to agree with the input.
   Reject invalid dates, excluded alias rows, and inputs that change mid-run.
5. Generate a workbook from checksum-pinned template and builder assets. Check
   ZIP integrity, XML validity, values, text postal codes, and protected parts.
6. Publish the artifacts and read them back before writing a completion marker.
   Record hashes, counts, input paths, and query identifiers in the audit.

## Arrival and recovery

An object-arrival event can start processing for the exact key. A periodic
reconciliation job provides recovery for missed events. Duplicate delivery is
expected, so completion state must be keyed to input identity. In a system with
concurrent workers, add an atomic claim or conditional write; content-addressed
paths alone do not prevent simultaneous execution.

Keep these states separate:

| State | Evidence required |
| --- | --- |
| Reviewed | Entity review and final references complete |
| Prepared | Output schema, values, and package checks pass |
| Published | Stored outputs are read back and verified |
| Submitted | Receiving system acknowledges the import |
| Reconciled | Downstream records match after the backfeed window |

A cloud-generated workbook does not establish that desktop Excel opened it.
A published artifact does not establish submission or downstream reconciliation.
Those require separate evidence.

## Tradeoffs

Exact input paths improve reproducibility but require batch-aware query
construction. Read-back checks add I/O but protect against premature success
markers. A polling fallback reduces dependence on event configuration while
adding scheduling cost. Deployment permission and trigger health are independent
of worker correctness; report each separately.
