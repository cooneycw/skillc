- **Wave fixture networking** (#621). Start the fixture on the existing wave
  network so Docker accepts its later per-role attachments. Explicitly marked
  controller-owned internal networks have an unverified description; other
  backend network labels and the default `none` network are unchanged. Physical
  multi-container qualification remains required.
