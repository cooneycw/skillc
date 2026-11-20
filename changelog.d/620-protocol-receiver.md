- Add the task-protocol receiver and the standalone `skillc-task-protocol`
  client: per-lease Unix endpoints, kernel peer credentials mapped to the
  observed runtime instance, decisions recorded at one elapsed reading before
  any receipt, unauthenticated ingress attributed to nobody, and coverage that
  turns UNKNOWN on any drop, capacity event or custody failure. Also lands the
  opt-in `DecideReplyChannel.set_peer_authorizer` gate (Refs #620).
