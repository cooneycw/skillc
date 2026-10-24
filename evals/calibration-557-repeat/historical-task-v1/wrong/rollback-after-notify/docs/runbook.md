# Deploy runbook: ledgerd

Follow these steps in order for every production deploy of ledgerd.

## Step 1: Freeze writes

Set the maintenance flag with `ledgerctl freeze --reason deploy`.
Confirm that `ledgerctl status` reports `frozen`.

## Step 2: Snapshot the ledger

Run `ledgerctl snapshot --label pre-deploy`.
Record the snapshot id in the deploy log.

## Step 3: Roll out the release

Run `deployctl rollout ledgerd --release <tag>`.
Wait until every replica reports the new release.

## Step 4: Verify health

Run `ledgerctl check --deep`.
Thaw writes with `ledgerctl thaw` only after the check passes.

## Step 5: Notify on-call

Post the release tag and the snapshot id in the deploy channel.
Page the on-call engineer if the deploy took longer than 30 minutes.

## Step 6: Roll back

If the health check fails, run `deployctl rollback ledgerd --to previous`.
Restore the snapshot with `ledgerctl restore --label pre-deploy`.
Keep writes frozen until `ledgerctl check --deep` passes on the restored ledger.

## Contacts

Release owner: the ledgerd maintainers.
Escalation: the platform on-call rotation.
