# F2 Status Artifact: Allocation Distance Matrix

**Status:** NOT_ESTIMABLE_FROM_FROZEN_CONFIRMATION
**Reason:** The finalized P8 runs schema (`data/results/p6_validity_runs.parquet`) records scalar `allocation_count` (integer) but does not preserve hourly job allocation vectors or schedule execution traces.
**Constraint Rule:** Per Phase 9 specification, normalized L1 allocation distance $D_{ij}(e) = \frac{||x_i - x_j||_1}{\max(||x_i||_1, ||x_j||_1, \epsilon)}$ requires comparable schedule vectors with identical indexing and units. Substituting `allocation_count` or fabricating vector data is strictly prohibited.
**Scientific Conclusion:** Policy allocation divergence cannot be quantitatively mapped from confirmation parquet rows alone.
