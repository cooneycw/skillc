# Gate-state controls

cases.json is the committed negative input population consumed by test_gate_state.py. These wire controls inject malformed data or controller failures; they do not claim that a model or real producer emitted them. The fresh and exact-join twins prove admission can succeed, and each refused input proves that the same consumer can refuse.

test_flow_check_route_task.py separately runs the actual pinned producer through the committed wrapper for honest resume, summary, seeded state and tampering. Only its uv/Python transport is adapted. No verdict or stage output is manufactured in those acceptance cases.

State bytes and complete output provide bounded equality evidence, not authenticated writer identity or candidate quiescence. Whole unseen stream forgery remains outside this boundary.
