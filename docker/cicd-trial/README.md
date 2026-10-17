# cicd runtime: one curl layer on the flow-check runtime (Refs #280)

The `cpp-codex-cicd-86641e8` profile needs the flow-check profile's offline
PyPI runtime plus `curl`, which CPP's `lib.cicd` health probe shells out to.
The shared trial image does not carry curl, and changing it would move every
receipt built from it. This image is that runtime plus exactly one layer.

```bash
python3 docker/profile-trial/build.py --receipt /tmp/base.json      # the flow-check runtime
python3 docker/cicd-trial/build.py --base-receipt /tmp/base.json --receipt /tmp/cicd.json
```

## Binding

`build.py` accepts only a base receipt that `skillc.runtime_supply` accepts as
a `profile-runtime` receipt. It builds `Dockerfile` (read from the committed
tree at HEAD) `FROM` the base image, then refuses to write a receipt unless:

1. the new image's layers are the base's layers plus exactly one;
2. `User`, `WorkingDir`, `Env`, `Entrypoint` and `Cmd` are the base's;
3. the runtime descriptor at `/usr/local/share/skillc/runtime-supply.json` is
   the base receipt's, byte for byte;
4. `curl --version`, run with `--network none`, names a version.

The base is reached through the local tag `skillc-cicd-base:<12 hex>`, which
the builder leaves in place: untagging an image's only name deletes it.

## Receipt

Closed schema, `target` `cicd-runtime`: the five identity keys, `image_id`,
`descriptor_sha256` (the base's), `recipe_sha256`, `source_commit`,
`base_receipt` (the whole base receipt, re-validated on every load),
`base_image_id` and `curl_version`. The controller selects it only for a
closure `runtime_supply.selected_runtime` assigns to `cicd-runtime`, and
refuses it for the flow-check runtime and vice versa.

Apt does not pin curl's version here, as the trial image does not pin its
other apt packages. The pin is the measured version in the receipt plus the
profile's `tool-curl` probe constraint (`>=7.0`), checked in every attempt's
preflight.

Offline controls: `tests/test_cicd_trial_image.py`. Real build and use:
`tests/test_cicd_profile_live.py`.
