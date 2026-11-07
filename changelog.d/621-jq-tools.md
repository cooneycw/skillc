- **Wave actor prerequisites** (#621). Supply jq in the shared trial image,
  declare and probe its JSON dependency, and add a dedicated jq-less image control.
  Physical wave failures retain compact per-role exit/reason/retirement summaries.
  Rebuild the physical image before rerunning qualification; no runtime isolation
  or actor outcome assertion is relaxed.
