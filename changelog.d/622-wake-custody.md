- Retain controller wake transitions in a sealed, hash-chained byte stream before
  dispatch. A separately held receipt verifies bounded content-addressed objects;
  poke counts and exit/refusal joins are derived from those bytes for offline use.
