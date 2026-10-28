- **Isolate load-harness attribution self-tests** (#462). Run ordinary pytest
  workers to completion before a separate serial invocation, preserving the
  unfiltered collection as authority and merging both required reports by exact
  identity. Missing, dropped, duplicated and incomplete lane evidence refuses;
  user selections remain supported. Harness verdicts and CPU-attribution bounds
  are unchanged, so external contention still yields INVALID.
